"""
Centralized MySQL connection pool manager.

Provides a single, shared connection pool for both API and ETL operations,
with connection timeouts, health checks, and retry logic for transient errors.

Retry strategy (production-grade):
  - Deadlock (1213):     fast retry,  short delays (deadlock resolves immediately)
  - Lock timeout (1205):  slow retry,  longer delays (holder needs time to release)
  - Connection errors:    medium retry, exponential backoff + full jitter
  - Circuit breaker:       opens after N consecutive failures, prevents cascading
"""

from __future__ import annotations

import logging
import random
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable, TypeVar

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

# ─────────────────────────────────────────────────────────────────────────────
# Global retry counter (for testing / monitoring)
# ─────────────────────────────────────────────────────────────────────────────

_total_retries: int = 0
_retry_lock: threading.Lock = threading.Lock()

# ─────────────────────────────────────────────────────────────────────────────
# Circuit breaker state
# ─────────────────────────────────────────────────────────────────────────────

_cb_state = {
    "consecutive_failures": 0,
    "consecutive_successes": 0,
    "last_failure_time": None,
    "state": "closed",  # closed=normal, open=blocking, half_open=probing
    "next_attempt_time": None,
}
_cb_lock = threading.Lock()


def get_retry_count() -> int:
    """Return the total number of retries triggered so far."""
    with _retry_lock:
        return _total_retries


def reset_retry_count() -> None:
    """Reset the global retry counter (call before a test scenario)."""
    with _retry_lock:
        global _total_retries
        _total_retries = 0


# ─────────────────────────────────────────────────────────────────────────────
# Pool configuration – tuned for concurrent read/write workloads
# ─────────────────────────────────────────────────────────────────────────────

POOL_SIZE = 20          # Baseline idle connections
MAX_OVERFLOW = 30       # Burst capacity (total max: 50)
POOL_RECYCLE = 1800     # Recycle connections every 30 min
POOL_TIMEOUT = 30       # Max seconds to wait for a connection from pool
POOL_PRE_PING = True    # Verify connection validity before each use
POOL_USE_LIFO = True   # Reuse recent connections (better cache locality)

# ─────────────────────────────────────────────────────────────────────────────
# Retry configuration – error-type-aware
# ─────────────────────────────────────────────────────────────────────────────

# --- Deadlock (1213): fast retry -----------------------------------------
# Deadlocks are detected and resolved by MySQL immediately, but the rows may
# still be locked by other transactions. Use a slightly higher base delay.
DEADLOCK_MAX_RETRIES = 5
DEADLOCK_BASE_DELAY = 0.3   # Give MySQL time to release row locks
DEADLOCK_MAX_DELAY = 3.0

# --- Lock wait timeout (1205): slow retry ---------------------------------
# Another transaction is holding the lock; need to wait longer.
LOCK_TIMEOUT_MAX_RETRIES = 3
LOCK_TIMEOUT_BASE_DELAY = 0.5
LOCK_TIMEOUT_MAX_DELAY = 10.0

# --- Connection errors: standard exponential backoff -------------------------
CONN_ERR_MAX_RETRIES = 3
CONN_ERR_BASE_DELAY = 0.5
CONN_ERR_MAX_DELAY = 15.0

# --- Jitter -----------------------------------------------------------------
# Full Jitter (AWS style):  sleep = random(0, base * 2^attempt)
# Equal Jitter (AWS style): sleep = base * 2^attempt / 2 + random(0, same)
# Decorrelated Jitter (Polly): sleep = random(base, sleep * 3)
JITTER_STRATEGY = "full"   # "full" | "equal" | "decorrelated"

# ─────────────────────────────────────────────────────────────────────────────
# Circuit breaker configuration
# ─────────────────────────────────────────────────────────────────────────────

CB_FAILURE_THRESHOLD = 10      # Open circuit after N consecutive failures
CB_SUCCESS_THRESHOLD = 2       # Close circuit after N consecutive successes
CB_OPEN_DURATION = 30          # Seconds to keep circuit open (half-open after)


# ─────────────────────────────────────────────────────────────────────────────
# Error classification
# ─────────────────────────────────────────────────────────────────────────────

class RetryStrategy:
    """Retry parameters tailored to a specific error type."""

    def __init__(
        self,
        max_retries: int,
        base_delay: float,
        max_delay: float,
        jitter_strategy: str = JITTER_STRATEGY,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter_strategy = jitter_strategy


# Pre-built strategies
STRATEGY_DEADLOCK = RetryStrategy(
    DEADLOCK_MAX_RETRIES, DEADLOCK_BASE_DELAY, DEADLOCK_MAX_DELAY,
)
STRATEGY_LOCK_TIMEOUT = RetryStrategy(
    LOCK_TIMEOUT_MAX_RETRIES, LOCK_TIMEOUT_BASE_DELAY, LOCK_TIMEOUT_MAX_DELAY,
)
STRATEGY_CONN_ERROR = RetryStrategy(
    CONN_ERR_MAX_RETRIES, CONN_ERR_BASE_DELAY, CONN_ERR_MAX_DELAY,
)

# Error type → strategy mapping
_ERROR_STRATEGY_MAP = {
    "1213": STRATEGY_DEADLOCK,        # ER_LOCK_DEADLOCK
    "1205": STRATEGY_LOCK_TIMEOUT,     # ER_LOCK_WAIT_TIMEOUT
    "deadlock": STRATEGY_DEADLOCK,
    "lock wait timeout": STRATEGY_LOCK_TIMEOUT,
    "connection reset": STRATEGY_CONN_ERROR,
    "lost connection": STRATEGY_CONN_ERROR,
    "too many connections": STRATEGY_CONN_ERROR,
    "server has gone away": STRATEGY_CONN_ERROR,
    "can't connect": STRATEGY_CONN_ERROR,
    "connection refused": STRATEGY_CONN_ERROR,
    # Pool queue full (sqlalchemy.exc.TimeoutError)
    "queue pool limit": STRATEGY_CONN_ERROR,
    "connection timed out": STRATEGY_CONN_ERROR,
    "timed out": STRATEGY_CONN_ERROR,
}


def classify_error(exc: BaseException) -> tuple[str, RetryStrategy]:
    """Classify a database error and return (error_type, retry_strategy)."""
    msg = str(exc).lower()

    # Check for specific MySQL error codes first
    for keyword, strategy in _ERROR_STRATEGY_MAP.items():
        if keyword in msg:
            if keyword in ("1213", "deadlock"):
                return "deadlock", strategy
            elif keyword in ("1205", "lock wait timeout"):
                return "lock_timeout", strategy
            else:
                return "conn_error", strategy

    return "unknown", STRATEGY_CONN_ERROR


# ─────────────────────────────────────────────────────────────────────────────
# Jitter implementations
# ─────────────────────────────────────────────────────────────────────────────

def compute_delay(
    attempt: int,
    strategy: RetryStrategy,
    prev_delay: float | None = None,
) -> float:
    """Compute retry delay (seconds) with the configured jitter strategy.

    Args:
        attempt:     Current attempt number (0-based).
        strategy:    RetryStrategy with base_delay / max_delay.
        prev_delay:  Previous delay (used by decorrelated jitter).

    Returns:
        Delay in seconds.
    """
    base = min(strategy.base_delay * (2 ** attempt), strategy.max_delay)

    if strategy.jitter_strategy == "full":
        # AWS Full Jitter: random(0, base)
        return random.uniform(0, base)

    elif strategy.jitter_strategy == "equal":
        # AWS Equal Jitter: base/2 + random(0, base/2)
        half = base / 2.0
        return half + random.uniform(0, half)

    elif strategy.jitter_strategy == "decorrelated":
        # Polly Decorrelated Jitter: random(base, prev * 3)
        low = strategy.base_delay
        high = (prev_delay * 3.0) if prev_delay else base
        return random.uniform(low, min(high, strategy.max_delay))

    else:
        return base  # No jitter


# ─────────────────────────────────────────────────────────────────────────────
# Circuit breaker
# ─────────────────────────────────────────────────────────────────────────────

def _cb_record_success() -> None:
    """Record a successful operation (circuit breaker)."""
    global _cb_state
    with _cb_lock:
        if _cb_state["state"] == "half_open":
            _cb_state["consecutive_successes"] = _cb_state.get("consecutive_successes", 0) + 1
            if _cb_state["consecutive_successes"] >= CB_SUCCESS_THRESHOLD:
                _cb_state["state"] = "closed"
                _cb_state["consecutive_failures"] = 0
                _cb_state["consecutive_successes"] = 0
                logger.warning("Circuit breaker: CLOSED (recovered)")
        elif _cb_state["state"] == "closed":
            _cb_state["consecutive_failures"] = 0
            _cb_state["consecutive_successes"] = 0


def _cb_record_failure() -> None:
    """Record a failed operation (circuit breaker)."""
    global _cb_state
    with _cb_lock:
        _cb_state["consecutive_failures"] += 1
        _cb_state["last_failure_time"] = datetime.now()

        if _cb_state["state"] == "half_open":
            _cb_state["state"] = "open"
            _cb_state["next_attempt_time"] = (
                datetime.now() + timedelta(seconds=CB_OPEN_DURATION)
            )
            logger.error(
                "Circuit breaker: RE-OPENED (probe failed, will retry in %ds)",
                CB_OPEN_DURATION,
            )
        elif (
            _cb_state["state"] == "closed"
            and _cb_state["consecutive_failures"] >= CB_FAILURE_THRESHOLD
        ):
            _cb_state["state"] = "open"
            _cb_state["next_attempt_time"] = (
                datetime.now() + timedelta(seconds=CB_OPEN_DURATION)
            )
            logger.error(
                "Circuit breaker: OPENED (≥%d consecutive failures, will probe in %ds)",
                CB_FAILURE_THRESHOLD, CB_OPEN_DURATION,
            )


def _cb_can_attempt() -> bool:
    """Check if we should attempt an operation (circuit breaker)."""
    with _cb_lock:
        if _cb_state["state"] == "closed":
            return True
        if _cb_state["state"] == "open":
            if (
                _cb_state["next_attempt_time"]
                and datetime.now() >= _cb_state["next_attempt_time"]
            ):
                _cb_state["state"] = "half_open"
                _cb_state["consecutive_successes"] = 0
                logger.warning("Circuit breaker: HALF-OPEN (probing...)")
                return True
            return False
        # half_open: allow exactly one probe
        return True


def get_circuit_breaker_state() -> dict:
    """Return current circuit breaker state (for monitoring)."""
    with _cb_lock:
        return {
            "state": _cb_state["state"],
            "consecutive_failures": _cb_state["consecutive_failures"],
            "last_failure": (
                _cb_state["last_failure_time"].isoformat()
                if _cb_state["last_failure_time"]
                else None
            ),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Engine (lazy singleton, thread-safe)
# ─────────────────────────────────────────────────────────────────────────────

_engine: Engine | None = None
_session_factory: Callable[[], Session] | None = None
_engine_lock = threading.Lock()


def get_engine() -> Engine:
    """Return the shared connection pool engine (create on first call).

    Thread-safe: uses double-checked locking to avoid race condition.
    """
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = create_engine(
                    settings.DATABASE_URL,
                    pool_size=POOL_SIZE,
                    max_overflow=MAX_OVERFLOW,
                    pool_recycle=POOL_RECYCLE,
                    pool_timeout=POOL_TIMEOUT,
                    pool_pre_ping=POOL_PRE_PING,
                    pool_use_lifo=POOL_USE_LIFO,
                    pool_reset_on_return="commit",
                    echo=False,
                    connect_args={
                        "connect_timeout": 15,
                        "read_timeout": 300,
                        "write_timeout": 300,
                        "charset": "utf8mb4",
                    },
                )
                logger.info(
                    "Shared connection pool created: pool_size=%d, max_overflow=%d, "
                    "max_total=%d, pool_timeout=%ds, lifo=%s, jitter=%s",
                    POOL_SIZE, MAX_OVERFLOW, POOL_SIZE + MAX_OVERFLOW,
                    POOL_TIMEOUT, POOL_USE_LIFO, JITTER_STRATEGY,
                )
    return _engine


def get_session_factory() -> Callable[[], Session]:
    """Return the shared ORM session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_engine(),
        )
    return _session_factory


def get_session() -> Session:
    """Create a new ORM session from the shared pool."""
    return get_session_factory()()


def dispose_engine() -> None:
    """Dispose the connection pool (call on app shutdown)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Connection pool disposed")


def get_pool_status() -> dict[str, Any]:
    """Return current pool statistics for monitoring.

    If the engine has not been created yet, returns a status indicating
    the pool is not initialized (rather than triggering lazy creation).

    Note: total_connections = checked_out + checked_in
          overflow(): negative = not yet warmed up,
                      0 = exactly pool_size,
                      positive = overflow connections active
    """
    engine = _engine  # Read once to avoid race
    if engine is None:
        return {
            "pool_size": POOL_SIZE,
            "checked_out": 0,
            "checked_in": 0,
            "overflow": -POOL_SIZE,  # All pool_size connections still to be created
            "total_connections": 0,
            "max_connections": POOL_SIZE + MAX_OVERFLOW,
            "engine_initialized": False,
            "circuit_breaker": get_circuit_breaker_state(),
        }

    pool = engine.pool
    checked_out = pool.checkedout()
    checked_in = pool.checkedin()
    raw_overflow = pool.overflow() if hasattr(pool, "overflow") else 0
    return {
        "pool_size": POOL_SIZE,
        "checked_out": checked_out,
        "checked_in": checked_in,
        "overflow": raw_overflow,
        "total_connections": checked_out + checked_in,
        "max_connections": POOL_SIZE + MAX_OVERFLOW,
        "engine_initialized": True,
        "circuit_breaker": get_circuit_breaker_state(),
    }


def warmup_pool(min_connections: int | None = None) -> dict[str, Any]:
    """Pre-create connections to avoid first-request latency.

    Args:
        min_connections: Minimum number of connections to create.
                        Defaults to POOL_SIZE (create all baseline connections).

    Returns:
        Dict with warmup result (created count, current pool status).
    """
    engine = get_engine()
    target = min_connections or POOL_SIZE
    created = 0
    sessions = []

    try:
        for i in range(target):
            session = Session(engine)
            # Execute a trivial query to actually open the TCP connection
            session.execute(text("SELECT 1"))
            sessions.append(session)
            created += 1

        logger.info("Pool warmup: created %d/%d connections", created, target)
        return {
            "status": "ok",
            "created": created,
            "target": target,
            "pool_status": get_pool_status(),
        }
    except Exception as exc:
        logger.error("Pool warmup failed: %s", exc)
        return {
            "status": "error",
            "created": created,
            "target": target,
            "error": str(exc),
        }
    finally:
        for session in sessions:
            try:
                session.close()
            except Exception:
                pass


def get_pool_config() -> dict[str, Any]:
    """Return current pool configuration parameters."""
    return {
        "pool_size": POOL_SIZE,
        "max_overflow": MAX_OVERFLOW,
        "pool_recycle": POOL_RECYCLE,
        "pool_timeout": POOL_TIMEOUT,
        "pool_pre_ping": POOL_PRE_PING,
        "pool_use_lifo": POOL_USE_LIFO,
        "pool_reset_on_return": "commit",
        "jitter_strategy": JITTER_STRATEGY,
        "deadlock_max_retries": DEADLOCK_MAX_RETRIES,
        "deadlock_base_delay": DEADLOCK_BASE_DELAY,
        "deadlock_max_delay": DEADLOCK_MAX_DELAY,
        "lock_timeout_max_retries": LOCK_TIMEOUT_MAX_RETRIES,
        "lock_timeout_base_delay": LOCK_TIMEOUT_BASE_DELAY,
        "lock_timeout_max_delay": LOCK_TIMEOUT_MAX_DELAY,
        "conn_err_max_retries": CONN_ERR_MAX_RETRIES,
        "conn_err_base_delay": CONN_ERR_BASE_DELAY,
        "conn_err_max_delay": CONN_ERR_MAX_DELAY,
        "cb_failure_threshold": CB_FAILURE_THRESHOLD,
        "cb_success_threshold": CB_SUCCESS_THRESHOLD,
        "cb_open_duration": CB_OPEN_DURATION,
    }


def reset_pool() -> dict[str, Any]:
    """Dispose and recreate the connection pool.

    This is useful when the pool is in a bad state (e.g., too many stale connections).
    WARNING: This will close all existing connections. In-flight transactions may be aborted.
    """
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
        _engine = None
        _session_factory = None
        logger.warning("Connection pool has been reset (all connections closed)")

    # Reset circuit breaker
    with _cb_lock:
        global _cb_state
        _cb_state["state"] = "closed"
        _cb_state["consecutive_failures"] = 0
        _cb_state["consecutive_successes"] = 0
        _cb_state["last_failure_time"] = None
        _cb_state["next_attempt_time"] = None

    # Reset retry counter
    reset_retry_count()

    logger.info("Connection pool reset complete – new connections will be created on demand")
    return {"status": "ok", "message": "Connection pool has been reset"}


def force_circuit_breaker_state(target_state: str) -> dict[str, Any]:
    """Manually force the circuit breaker to a specific state.

    Args:
        target_state: "open" | "closed" | "half_open"

    Returns:
        Status dict.
    """
    if target_state not in ("open", "closed", "half_open"):
        raise ValueError(f"Invalid state: {target_state}. Must be open/closed/half_open.")

    with _cb_lock:
        global _cb_state
        old_state = _cb_state["state"]
        _cb_state["state"] = target_state

        if target_state == "closed":
            _cb_state["consecutive_failures"] = 0
            _cb_state["consecutive_successes"] = 0
            _cb_state["next_attempt_time"] = None
        elif target_state == "open":
            _cb_state["next_attempt_time"] = (
                datetime.now() + timedelta(seconds=CB_OPEN_DURATION)
            )
        elif target_state == "half_open":
            _cb_state["consecutive_successes"] = 0
            _cb_state["next_attempt_time"] = None

        logger.warning(
            "Circuit breaker manually forced: %s → %s",
            old_state, target_state,
        )

    return {
        "status": "ok",
        "old_state": old_state,
        "new_state": target_state,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Retry helpers (production-grade)
# ─────────────────────────────────────────────────────────────────────────────

def is_retryable_error(exc: BaseException) -> bool:
    """Check if an exception is a transient MySQL error that is safe to retry.

    Only retries on SQLAlchemy OperationalError or MySQLdb operational errors,
    to avoid accidentally retrying non-transient errors.
    """
    # Only retry on known transient database errors
    # OperationalError covers most transient MySQL errors (deadlock, timeout, etc.)
    # Connection errors may also appear as other exception types with specific messages
    msg = str(exc).lower()

    # Always retry on OperationalError with known error codes/keywords
    if isinstance(exc, OperationalError):
        return any(kw in msg for kw in _ERROR_STRATEGY_MAP)

    # For non-OperationalError, only retry on explicit connection-related messages
    # This avoids retrying on programming errors, integrity errors, etc.
    conn_keywords = (
        "too many connections", "connection reset", "lost connection",
        "server has gone away", "can't connect", "connection refused",
        "queue pool limit", "connection timed out", "timed out",
    )
    return any(kw in msg for kw in conn_keywords)


def execute_with_retry(
    operation: Callable[[], T],
    max_retries: int | None = None,
    base_delay: float | None = None,
    max_delay: float | None = None,
    operation_name: str = "db operation",
) -> T:
    """Execute a callable with automatic retry on transient MySQL errors.

    Uses error-type-aware retry strategy:
      - Deadlock (1213):     fast,  short delays (deadlock already resolved)
      - Lock timeout (1205):  slower, longer delays
      - Connection errors:    standard exponential backoff + full jitter

    Args:
        operation:      A callable that performs the database operation.
        max_retries:    Override default max retries (None = auto by error type).
                        When None, the retry count is determined by the error type
                        on the first failure.
        base_delay:      Override default base delay (None = auto by error type).
        max_delay:       Override default max delay (None = auto by error type).
        operation_name:  Human-readable name for log messages.

    Returns:
        The return value of the operation callable.

    Raises:
        The original exception if all retries are exhausted or error is non-retryable.
        CircuitBreakerOpenError: if circuit breaker is open.
    """
    # Check circuit breaker
    if not _cb_can_attempt():
        state = get_circuit_breaker_state()
        raise CircuitBreakerOpenError(
            f"Circuit breaker is {state['state']} – "
            f"last failure: {state.get('last_failure', 'N/A')}"
        )

    last_exc: BaseException | None = None
    prev_delay: float | None = None
    attempt = 0
    actual_max: int | None = max_retries  # None until first failure classifies it
    actual_base: float | None = base_delay
    actual_max_delay: float | None = max_delay
    error_type: str = "unknown"

    while True:
        try:
            result = operation()

            # Success – record for circuit breaker
            _cb_record_success()

            if attempt > 0:
                logger.info(
                    "[%s] Succeeded after %d retry(ies)",
                    operation_name, attempt,
                )
            return result

        except Exception as exc:
            last_exc = exc

            # Non-retryable → fail immediately
            if not is_retryable_error(exc):
                _cb_record_failure()
                raise

            # Determine strategy for this error type (first failure sets the budget)
            error_type, strategy = classify_error(exc)
            if actual_max is None:
                actual_max = strategy.max_retries
                actual_base = strategy.base_delay if base_delay is None else base_delay
                actual_max_delay = strategy.max_delay if max_delay is None else max_delay

            if attempt < actual_max:
                # Global retry counter +1
                with _retry_lock:
                    global _total_retries
                    _total_retries += 1

                # Compute delay with jitter
                strategy_override = RetryStrategy(
                    actual_max, actual_base, actual_max_delay, JITTER_STRATEGY,
                )
                delay = compute_delay(attempt, strategy_override, prev_delay)
                prev_delay = delay

                logger.warning(
                    "[%s] %s (attempt %d/%d): %s. "
                    "Retrying in %.2fs (jitter=%s)...",
                    operation_name, error_type.upper(),
                    attempt + 1, actual_max, exc, delay, JITTER_STRATEGY,
                )
                time.sleep(delay)
                attempt += 1
            else:
                # Exhausted retries
                _cb_record_failure()
                logger.error(
                    "[%s] %s – all %d retries exhausted, giving up: %s",
                    operation_name, error_type.upper(), actual_max, exc,
                )
                raise

    # Unreachable, but keeps mypy happy
    assert last_exc is not None
    raise last_exc


class CircuitBreakerOpenError(Exception):
    """Raised when the circuit breaker is open (database appears unavailable)."""
    pass
