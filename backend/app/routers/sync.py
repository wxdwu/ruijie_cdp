"""
ETL Sync API routes.

Provides 4 endpoints:
- POST /api/admin/etl/full         – Trigger full sync
- POST /api/admin/etl/increment  – Trigger incremental sync
- GET  /api/admin/etl/status       – Get latest sync status
- GET  /api/admin/etl/history      – Get sync history
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.etl.etl_sync import run_full_sync, run_incremental_sync
from app.services.etl.sync_status import get_sync_status, get_sync_history

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/etl", tags=["etl-sync"])


# ─────────────────────────────────────────────────────────────────────────────
# Request / Response models
# ─────────────────────────────────────────────────────────────────────────────

class SyncTriggerResponse(BaseModel):
    status: str
    sync_id: int
    message: str


class SyncStatusResponse(BaseModel):
    sync_id: Optional[int] = None
    sync_type: Optional[str] = None
    trigger_by: Optional[str] = None
    status: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    elapsed_seconds: Optional[float] = None
    rows_synced: Optional[int] = None
    error_message: Optional[str] = None


class SyncHistoryItem(BaseModel):
    sync_id: int
    sync_type: str
    trigger_by: Optional[str] = None
    status: str
    start_time: datetime
    end_time: Optional[datetime] = None
    elapsed_seconds: Optional[float] = None
    rows_synced: int = 0
    error_message: Optional[str] = None


class SyncHistoryResponse(BaseModel):
    total: int
    records: List[SyncHistoryItem]


# ─────────────────────────────────────────────────────────────────────────────
# API Endpoints（仅做编排，业务逻辑委托 etl_sync / sync_status 服务）
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/full", response_model=SyncTriggerResponse)
async def trigger_full_sync(
    trigger_by: str = Query("system", description="触发人"),
):
    """Trigger full sync (TRUNCATE + full reload)."""
    try:
        stats = await asyncio.to_thread(run_full_sync, trigger_by)
    except Exception as exc:
        logger.exception("Full sync failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Full sync failed: {exc}")

    if stats.get("status") == "skipped":
        running = stats.get("running_sync") or {}
        raise HTTPException(
            status_code=409,
            detail=(
                f"当前有同步任务正在进行（类型：{running.get('type', '未知')}，"
                f"触发人：{running.get('trigger_by', '未知')}），请稍后重试"
            ),
        )

    return {
        "status": "ok",
        "sync_id": stats.get("log_id", 0),
        "message": f"Full sync completed in {stats.get('elapsed_seconds', 0)}s",
    }


@router.post("/increment", response_model=SyncTriggerResponse)
async def trigger_increment_sync(
    trigger_by: str = Query("system", description="触发人"),
):
    """Trigger incremental sync (UPSERT + delete detection)."""
    try:
        stats = await asyncio.to_thread(run_incremental_sync, trigger_by)
    except Exception as exc:
        logger.exception("Incremental sync failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Incremental sync failed: {exc}")

    if stats.get("status") == "skipped":
        running = stats.get("running_sync") or {}
        raise HTTPException(
            status_code=409,
            detail=(
                f"当前有同步任务正在进行（类型：{running.get('type', '未知')}，"
                f"触发人：{running.get('trigger_by', '未知')}），请稍后重试"
            ),
        )

    return {
        "status": "ok",
        "sync_id": stats.get("log_id", 0),
        "message": f"Incremental sync completed in {stats.get('elapsed_seconds', 0)}s",
    }


@router.post("/scheduler-full-test", response_model=SyncTriggerResponse)
async def test_scheduled_full_sync(
    no_retry: bool = Query(False, description="true=不重试，直接复现单次真实失败原因（便于定位）"),
):
    """测试接口：手动模拟一次「定时全量同步」的执行体（与调度器调用同一套代码）。

    - 与 etl_scheduler._scheduled_full_sync 复用同一逻辑（run_full_sync +
      上游未就绪重试 + 写 dws_sync_obs），用于验证定时链路、定位定时专属问题。
    - no_retry=true 时关闭重试，让单次真实失败原因直接暴露（如上游窗口导致的
      0 行校验失败），不用等重试窗口，便于快速定位。
    注意：本接口会真实触发一次全量同步（数据写入），仅用于测试/排查，勿高频调用。
    """
    from app.services.etl.etl_scheduler import _run_scheduled_full_sync

    try:
        result = await asyncio.to_thread(_run_scheduled_full_sync, allow_retry=not no_retry)
    except Exception as exc:  # 兜底，理论上 _run_scheduled_full_sync 内部已吞异常
        logger.exception("scheduler-full-test failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Scheduler full test failed: {exc}")

    if result.get("status") == "skipped":
        raise HTTPException(
            status_code=409,
            detail="当前有同步任务正在进行，请稍后重试",
        )
    if result.get("status") == "failed":
        raise HTTPException(
            status_code=500,
            detail=f"Scheduler full test failed（attempt={result.get('attempt')}）: {result.get('error')}",
        )

    return {
        "status": "ok",
        "sync_id": 0,  # 测试接口不直接返回 log_id，可配合 GET /status 查看最新记录
        "message": f"Scheduler full test passed in {result.get('attempt')} attempt(s)",
    }


@router.get("/status")
async def get_sync_status_endpoint():
    """Get the latest sync status（委托 sync_status 服务查询 dws_sync_log）。"""
    try:
        return get_sync_status()
    except Exception as exc:
        logger.exception("get_sync_status failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/history", response_model=SyncHistoryResponse)
async def get_sync_history_endpoint(
    limit: int = Query(10, ge=1, le=100, description="Number of records to return"),
):
    """Get sync history（委托 sync_status 服务查询 dws_sync_log）。"""
    try:
        return get_sync_history(limit)
    except Exception as exc:
        logger.exception("get_sync_history failed")
        raise HTTPException(status_code=500, detail=str(exc))
