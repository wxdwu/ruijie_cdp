"""
聚合表数据规模监控 API。

端点（前缀 /api/admin/monitor）：
  POST /run     – 触发一次监控：统计所有已注册表的数据量并写入 dws_sync_obs
  GET  /latest  – 返回每个表最近一次监控到的数据量快照
  GET  /history – 返回最近的监控历史记录（按时间倒序）
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.monitor.monitor_service import (
    get_latest_obs,
    get_latest_snapshot,
    run_monitor,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/monitor", tags=["monitor"])


@router.post("/run")
def trigger_monitor(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """触发一次表监控：统计所有已注册表的数据量并写入 dws_sync_obs。"""
    try:
        records = run_monitor(db)
        return {"status": "ok", "count": len(records), "records": records}
    except Exception as exc:
        logger.exception("monitor run failed")
        raise HTTPException(status_code=500, detail=f"monitor run failed: {exc}")


@router.get("/latest")
def latest_snapshot(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """返回每个表最近一次（最新）监控到的数据量快照。"""
    try:
        return {"status": "ok", "snapshot": get_latest_snapshot(db)}
    except Exception as exc:
        logger.exception("monitor latest failed")
        raise HTTPException(status_code=500, detail=f"monitor latest failed: {exc}")


@router.get("/history")
def monitor_history(
    limit: int = Query(100, ge=1, le=1000, description="返回最近多少条历史记录"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """返回最近的监控历史记录（按时间倒序）。"""
    try:
        return {"status": "ok", "records": get_latest_obs(db, limit)}
    except Exception as exc:
        logger.exception("monitor history failed")
        raise HTTPException(status_code=500, detail=f"monitor history failed: {exc}")
