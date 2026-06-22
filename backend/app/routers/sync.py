"""
Sync API routes – V2.

Provides 4 endpoints:
- POST /api/sync/full         – Trigger full sync
- POST /api/sync/incremental  – Trigger incremental sync
- GET  /api/sync/status       – Get latest sync status
- GET  /api/sync/history      – Get sync history
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.etl_sync_v2 import run_full_sync, run_incremental_sync, get_etl_engine
from sqlalchemy import text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sync", tags=["sync"])

# Concurrency lock – prevent overlapping syncs
_etl_lock = asyncio.Lock()


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
    id: int
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
# API Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/full", response_model=SyncTriggerResponse)
async def trigger_full_sync(
    trigger_by: str = Query("system", description="触发人"),
):
    """Trigger full sync (TRUNCATE + full reload)."""
    if _etl_lock.locked():
        raise HTTPException(status_code=409, detail="A sync run is already in progress. Please wait.")
    async with _etl_lock:
        try:
            stats = await asyncio.to_thread(run_full_sync, trigger_by)
            return {
                "status": "ok",
                "sync_id": stats.get("log_id", 0),
                "message": f"Full sync completed in {stats.get('elapsed_seconds', 0)}s",
            }
        except Exception as exc:
            logger.exception("Full sync failed: %s", exc)
            raise HTTPException(status_code=500, detail=f"Full sync failed: {exc}")


@router.post("/incremental", response_model=SyncTriggerResponse)
async def trigger_incremental_sync(
    trigger_by: str = Query("system", description="触发人"),
):
    """Trigger incremental sync (UPSERT + delete detection)."""
    if _etl_lock.locked():
        raise HTTPException(status_code=409, detail="A sync run is already in progress. Please wait.")
    async with _etl_lock:
        try:
            stats = await asyncio.to_thread(run_incremental_sync, trigger_by)
            return {
                "status": "ok",
                "sync_id": stats.get("log_id", 0),
                "message": f"Incremental sync completed in {stats.get('elapsed_seconds', 0)}s",
            }
        except Exception as exc:
            logger.exception("Incremental sync failed: %s", exc)
            raise HTTPException(status_code=500, detail=f"Incremental sync failed: {exc}")


@router.get("/status")
async def get_sync_status():
    """Get the latest sync status."""
    try:
        engine = get_etl_engine()
        with engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT id, sync_type, trigger_by, status, "
                    "  start_time, end_time, "
                    "  TIMESTAMPDIFF(SECOND, start_time, end_time) AS elapsed_seconds, "
                    "  rows_synced, error_message "
                    "FROM dws_sync_log "
                    "ORDER BY id DESC "
                    "LIMIT 1"
                )
            )
            row = result.fetchone()
        if not row:
            return {"status": "no_sync_found"}
        return {
            "sync_id": row[0],
            "sync_type": row[1],
            "trigger_by": row[2],
            "status": row[3],
            "start_time": str(row[4]) if row[4] else None,
            "end_time": str(row[5]) if row[5] else None,
            "elapsed_seconds": row[6],
            "rows_synced": row[7],
            "error_message": row[8],
        }
    except Exception as exc:
        logger.exception("get_sync_status failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/history", response_model=SyncHistoryResponse)
async def get_sync_history(
    limit: int = Query(10, ge=1, le=100, description="Number of records to return"),
):
    """Get sync history."""
    engine = get_etl_engine()
    with engine.connect() as conn:
        total_result = conn.execute(text("SELECT COUNT(*) FROM dws_sync_log"))
        total = total_result.fetchone()[0]
        result = conn.execute(
            text(
                "SELECT id, sync_type, trigger_by, status, "
                "  start_time, end_time, "
                "  TIMESTAMPDIFF(SECOND, start_time, end_time) AS elapsed_seconds, "
                "  rows_synced, error_message "
                "FROM dws_sync_log "
                "ORDER BY id DESC "
                "LIMIT :limit"
            ),
            {"limit": limit},
        )
        rows = result.fetchall()
    records = [
        {
            "id": row[0],
            "sync_type": row[1],
            "trigger_by": row[2],
            "status": row[3],
            "start_time": str(row[4]) if row[4] else None,
            "end_time": str(row[5]) if row[5] else None,
            "elapsed_seconds": row[6],
            "rows_synced": row[7] or 0,
            "error_message": row[8],
        }
        for row in rows
    ]
    return {"total": total, "records": records}
