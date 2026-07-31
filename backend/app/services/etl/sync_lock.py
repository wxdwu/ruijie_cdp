"""全局同步互斥锁（跨进程 + 进程内）。

全量同步 / 增量同步 / 定时调度触发的同步，必须保证在『所有 worker / 进程』
范围内同一时刻只有一个运行。

实现分两层：
1. 进程内 threading.Lock：同进程内快速拒绝（手动触发线程与调度器线程互斥）。
2. MySQL advisory lock（GET_LOCK / RELEASE_LOCK）：跨进程互斥，覆盖“重复启动
   uvicorn / 多 worker / --reload 残留旧 worker”等进程内锁无力覆盖的场景。

advisory lock 由一把『专属连接』在同步全程持有，end_sync 时 RELEASE_LOCK 并
归还连接；进程崩溃时 MySQL 也会在连接断开后自动释放，不会造成死锁残留。

说明：同步函数（run_full_sync / run_incremental_sync）经由 asyncio.to_thread
或在调度器独立线程中执行，因此仍需兼顾跨线程与跨进程两种并发。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from sqlalchemy import text

from app.database.engine import get_engine

logger = logging.getLogger(__name__)

# ── 进程内互斥（快速拒绝） ────────────────────────────────────────────────
_sync_lock = threading.Lock()
# 信息锁：保护 _running 字典的读写，避免与互斥锁相互阻塞
_info_lock = threading.RLock()
_running: dict = {"type": None, "trigger_by": None, "started_at": None}

# ── 跨进程互斥（MySQL advisory lock） ──────────────────────────────────────
# 全局唯一锁名
_DB_LOCK_NAME = "etl_sync_global"
# 持有 advisory lock 的专属连接（全程持有，end_sync 释放）；复用主引擎连接，
# 自动继承 charset 等 connect_args，且只额外占用主池 1 个槽位（同步自身 _exec
# 即用即还），默认池容量足够。
_lock_conn = None


def _acquire_db_lock() -> bool:
    """跨进程获取 MySQL advisory lock（非阻塞）。

    返回 True 表示获取成功；返回 False 表示已被其他进程持有（立即跳过，不阻塞）。
    进程崩溃时 MySQL 会在连接断开后自动释放该锁。
    """
    global _lock_conn
    engine = get_engine()
    conn = engine.connect()
    try:
        # timeout=0：立即返回不阻塞；1=获取成功，0=已被其他进程持有，NULL=错误
        got = conn.execute(
            text("SELECT GET_LOCK(:name, 0)"), {"name": _DB_LOCK_NAME}
        ).scalar()
        if got != 1:
            conn.close()
            return False
        # 抬高会话 wait_timeout，防止长同步（数十分钟）期间该专属连接被 MySQL
        # 因空闲超时而踢掉、导致锁提前丢失而并发放行。
        conn.execute(text("SET SESSION wait_timeout = 86400"))
        _lock_conn = conn
        return True
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        raise


def _release_db_lock() -> None:
    """释放 MySQL advisory lock 并归还专属连接。"""
    global _lock_conn
    if _lock_conn is not None:
        try:
            _lock_conn.execute(
                text("SELECT RELEASE_LOCK(:name)"), {"name": _DB_LOCK_NAME}
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("释放 advisory lock 失败（连接可能已断开）: %s", exc)
        finally:
            try:
                _lock_conn.close()
            except Exception:
                pass
            _lock_conn = None


def try_begin_sync(sync_type: str, trigger_by: str) -> tuple[bool, Optional[dict]]:
    """尝试获取全局同步锁（进程内 + 跨进程两层）。

    成功返回 (True, None)；失败返回 (False, 当前正在运行的同步信息 dict)，
    调用方据此跳过本次同步并给出提示。
    """
    # 第一层：进程内快速拒绝
    if not _sync_lock.acquire(blocking=False):
        with _info_lock:
            info = dict(_running) if _running.get("type") else None
        return False, info

    # 第二层：跨进程 advisory lock
    try:
        if not _acquire_db_lock():
            _sync_lock.release()
            # 被其他进程持有：本进程无对应运行信息，给出“外部实例”提示。
            return False, {
                "type": "其他进程实例",
                "trigger_by": "未知",
                "started_at": None,
            }
    except Exception as exc:
        # 拿不到跨进程锁（DB 异常）时，保守地拒绝本次同步，避免并发破坏数据。
        logger.warning(
            "获取跨进程 advisory lock 失败，为数据安全拒绝本次同步: %s", exc
        )
        _sync_lock.release()
        return False, {
            "type": "其他进程实例(获取锁异常)",
            "trigger_by": "未知",
            "started_at": None,
        }

    with _info_lock:
        _running["type"] = sync_type
        _running["trigger_by"] = trigger_by
        _running["started_at"] = time.time()
    return True, None


def end_sync() -> None:
    """释放全局同步锁（先跨进程，再进程内）。"""
    with _info_lock:
        _running["type"] = None
        _running["trigger_by"] = None
        _running["started_at"] = None
    _release_db_lock()
    _sync_lock.release()


def get_running_sync() -> Optional[dict]:
    """返回当前正在运行的同步信息（无则返回 None）。"""
    with _info_lock:
        return dict(_running) if _running.get("type") else None
