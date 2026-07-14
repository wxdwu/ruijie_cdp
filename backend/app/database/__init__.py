# app/database 子包入口。
# 由原 app/connection_pool.py（连接池基础设施）与 app/database.py（ORM 会话封装）收拢而来：
#   - engine.py : 引擎 / 连接池 / 重试 / 熔断 / 池状态（原 connection_pool）
#   - session.py: SessionLocal / get_db / Base（原 database）
# 保持既有 `from app.database import get_db` 等引用兼容。

from app.database.engine import (
    get_engine,
    get_session,
    get_session_factory,
    dispose_engine,
    get_pool_status,
    get_pool_config,
    warmup_pool,
    reset_pool,
    force_circuit_breaker_state,
    get_retry_count,
    reset_retry_count,
    get_circuit_breaker_state,
    execute_with_retry,
    is_retryable_error,
    classify_error,
    compute_delay,
    CircuitBreakerOpenError,
    POOL_SIZE,
    MAX_OVERFLOW,
    POOL_TIMEOUT,
    POOL_RECYCLE,
)
from app.database.session import get_db, SessionLocal, engine, Base

__all__ = [
    "get_engine", "get_session", "get_session_factory", "dispose_engine",
    "get_pool_status", "get_pool_config", "warmup_pool", "reset_pool",
    "force_circuit_breaker_state", "get_retry_count", "reset_retry_count",
    "get_circuit_breaker_state", "execute_with_retry", "is_retryable_error",
    "classify_error", "compute_delay", "CircuitBreakerOpenError",
    "POOL_SIZE", "MAX_OVERFLOW", "POOL_TIMEOUT", "POOL_RECYCLE",
    "get_db", "SessionLocal", "engine", "Base",
]
