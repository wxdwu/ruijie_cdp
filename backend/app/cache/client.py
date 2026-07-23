"""Redis 客户端的创建、复用、关闭与健康检查。

本模块只负责“怎样连接 Redis”，不包含具体缓存键和业务数据的读写规则。
应用进程内的所有缓存服务共享同一个 ``redis.Redis`` 实例及其连接池；如果
缓存被关闭或 Redis 暂时不可用，上层缓存服务会采用 fail-open 策略回退到数据库。
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional

import redis

from app.config import settings

logger = logging.getLogger(__name__)

# 进程级 Redis 客户端。redis-py 的 Redis 对象内部维护线程安全的连接池，
# 因而无需为每次 HTTP 请求重新创建客户端。
_client: Optional[redis.Redis] = None

# 保护客户端的首次创建与关闭，避免多个工作线程同时修改全局 _client。
_client_lock = threading.Lock()


def get_cache_client() -> Optional[redis.Redis]:
    """返回进程共享的 Redis 客户端；缓存关闭时返回 ``None``。

    这里使用“双重检查锁”：大多数请求直接读取已经创建好的客户端，只有第一次
    初始化时才进入线程锁。``from_url`` 只建立客户端和连接池，真正的网络连接通常
    会在第一次执行 Redis 命令时按需创建。
    """
    # 配置开关优先级最高。返回 None 让上层明确走 BYPASS，而不是访问 Redis。
    if not settings.CACHE_ENABLED:
        return None

    global _client
    if _client is None:
        with _client_lock:
            # 等待锁期间，其他线程可能已经完成初始化，因此进入锁后必须再次检查。
            if _client is None:
                _client = redis.Redis.from_url(
                    settings.CACHE_URL,
                    # 保留 bytes，由缓存服务统一负责 UTF-8 与 JSON 解码。
                    decode_responses=False,
                    # 配置以毫秒保存，redis-py 的超时参数以秒为单位。
                    socket_connect_timeout=settings.CACHE_CONNECT_TIMEOUT_MS / 1000,
                    socket_timeout=settings.CACHE_READ_TIMEOUT_MS / 1000,
                    max_connections=settings.CACHE_MAX_CONNECTIONS,
                    # 长连接空闲一段时间后，复用前先检查连接是否健康。
                    health_check_interval=30,
                )
                logger.info("Redis cache client created: enabled=true")
    return _client


def close_cache_client() -> None:
    """关闭共享客户端和连接池，供 FastAPI lifespan 退出阶段调用。"""
    global _client
    with _client_lock:
        if _client is None:
            return
        try:
            # close() 关闭客户端；disconnect() 确保池中的现有连接全部断开。
            _client.close()
            _client.connection_pool.disconnect()
        except Exception as exc:  # cache shutdown must never block app shutdown
            logger.warning("Failed to close Redis cache client: %s", exc)
        finally:
            # 即使关闭过程中出现异常，也清空引用，避免后续复用不确定状态的客户端。
            _client = None


def get_cache_status() -> dict[str, Any]:
    """返回 ``/api/health`` 使用的非致命缓存健康状态。

    Redis 是性能组件而非数据真源，所以连接失败只报告 ``degraded``，不会在这里
    抛出异常导致整个应用健康检查失败。
    """
    if not settings.CACHE_ENABLED:
        return {"enabled": False, "status": "disabled"}
    try:
        client = get_cache_client()
        if client is None:
            return {"enabled": True, "status": "degraded"}
        # PING 会实际借用连接池中的连接，因此能发现网络和认证问题。
        client.ping()
        return {"enabled": True, "status": "ok"}
    except Exception as exc:
        logger.warning("Redis cache health check failed: %s", exc)
        return {"enabled": True, "status": "degraded"}
