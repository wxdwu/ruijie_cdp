"""
Connection Pool Management API routes.

Provides operational endpoints for monitoring and managing the MySQL connection pool:

- GET  /api/pool/status           – Get pool statistics (connections, circuit breaker)
- GET  /api/pool/config           – Get pool configuration parameters
- POST /api/pool/reset            – Dispose and recreate the pool (dangerous!)
- POST /api/pool/circuit-breaker/open   – Manually open the circuit breaker
- POST /api/pool/circuit-breaker/close  – Manually close the circuit breaker
- POST /api/pool/circuit-breaker/half-open – Manually set to half-open (probe)
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from app.database.engine import (
    get_pool_status,
    get_pool_config,
    reset_pool,
    force_circuit_breaker_state,
    get_retry_count,
    reset_retry_count,
    warmup_pool,
    POOL_SIZE,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pool", tags=["connection-pool"])


# ─────────────────────────────────────────────────────────────────────────────
# Response models
# ─────────────────────────────────────────────────────────────────────────────

# Using Dict/Any for flexibility; for stricter typing, define Pydantic models here.


# ─────────────────────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/status")
def pool_status() -> Dict[str, Any]:
    """Get connection pool runtime statistics.

    Returns:
        pool_size, checked_out, checked_in, overflow, total_connections,
        max_connections, circuit_breaker state.
    """
    return get_pool_status()


@router.get("/config")
def pool_config() -> Dict[str, Any]:
    """Get connection pool configuration parameters.

    Returns:
        All pool / retry / circuit-breaker tuning parameters.
    """
    return get_pool_config()


@router.get("/stats")
def pool_stats() -> Dict[str, Any]:
    """Get extended pool statistics (status + config + retry count).

    This is a convenience endpoint that bundles status + config + retry counter.
    """
    return {
        **get_pool_status(),
        "config": get_pool_config(),
        "retry_count": get_retry_count(),
    }


@router.post("/reset")
def pool_reset(confirm: bool = False) -> Dict[str, Any]:
    """Reset the connection pool (close all connections, recreate on demand).

    WARNING: This will abort in-flight transactions. Use only during maintenance
    or when the pool is in a bad state.

    Args:
        confirm: Must be True to actually perform the reset (safety flag).
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Set confirm=True to confirm this dangerous operation.",
        )

    logger.warning("Manual pool reset triggered via API")
    return reset_pool()


@router.post("/circuit-breaker/{target_state}")
def circuit_breaker_force(target_state: str) -> Dict[str, Any]:
    """Manually force the circuit breaker to a specific state.

    This is useful for operational scenarios:
    - "open":      Stop all DB traffic (e.g., downstream DB is known to be down)
    - "closed":    Force traffic to resume (e.g., after manual DB recovery)
    - "half_open": Allow exactly one probe request through

    Args:
        target_state: "open" | "closed" | "half_open"
    """
    if target_state not in ("open", "closed", "half_open"):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid state: {target_state}. Must be open/closed/half_open.",
        )

    try:
        return force_circuit_breaker_state(target_state)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/retry-counter/reset")
def retry_counter_reset() -> Dict[str, Any]:
    """Reset the global retry counter (for testing / metrics)."""
    old_count = get_retry_count()
    reset_retry_count()
    return {"status": "ok", "old_count": old_count, "message": "Retry counter reset to 0"}


@router.post("/warmup")
def pool_warmup(min_connections: int | None = None) -> Dict[str, Any]:
    """Pre-create connections to avoid first-request latency.

    Call this endpoint after app startup to warm up the pool.

    Args:
        min_connections: Number of connections to pre-create.
                        Defaults to pool_size (20). Must not exceed pool_size.
    """
    if min_connections is not None and min_connections > POOL_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"min_connections ({min_connections}) exceeds pool_size ({POOL_SIZE})",
        )
    return warmup_pool(min_connections)
