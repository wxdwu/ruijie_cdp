"""
ElasticSearch 同步管理 API

端点：
  POST /api/admin/es/full      – 触发 ES 全量同步
  POST /api/admin/es/increment – 触发 ES 增量同步
  GET  /api/admin/es/health    – ES 连接与索引状态
"""

import asyncio
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services import es_sync

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/es", tags=["elasticsearch-sync"])

_es_lock = asyncio.Lock()


class EsSyncResponse(BaseModel):
    status: str
    message: str
    details: Optional[Dict[str, Any]] = None


@router.post("/full", response_model=EsSyncResponse)
async def trigger_es_full(trigger_by: str = Query("system", description="触发人")):
    """触发 ES 全量同步（重建所有 DWS 索引）。"""
    if _es_lock.locked():
        raise HTTPException(status_code=409, detail="An ES sync is already in progress.")
    async with _es_lock:
        try:
            stats = await asyncio.to_thread(es_sync.run_es_full_sync)
            return {"status": "ok", "message": "ES full sync completed", "details": stats}
        except Exception as exc:
            logger.exception("ES full sync failed")
            raise HTTPException(status_code=500, detail=f"ES full sync failed: {exc}")


@router.post("/increment", response_model=EsSyncResponse)
async def trigger_es_increment(trigger_by: str = Query("system", description="触发人")):
    """触发 ES 增量同步（基于水位 upsert）。"""
    if _es_lock.locked():
        raise HTTPException(status_code=409, detail="An ES sync is already in progress.")
    async with _es_lock:
        try:
            stats = await asyncio.to_thread(es_sync.run_es_incremental_sync)
            return {"status": "ok", "message": "ES incremental sync completed", "details": stats}
        except Exception as exc:
            logger.exception("ES incremental sync failed")
            raise HTTPException(status_code=500, detail=f"ES incremental sync failed: {exc}")


@router.get("/health")
async def es_health():
    """检查 ES 连接与各索引状态。"""
    try:
        info = await asyncio.to_thread(es_sync.get_es_health)
        return info
    except Exception as exc:
        logger.exception("ES health check failed")
        raise HTTPException(status_code=500, detail=str(exc))
