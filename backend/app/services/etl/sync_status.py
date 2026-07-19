"""ETL 同步状态查询服务。

集中读取 dws_sync_log 的审计状态/历史，供 etl 路由与调度器复用，
避免在路由层直接写 SQL（保持 router 只负责编排）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app.services.etl.etl_sync import get_etl_engine


# dws_sync_log 列顺序（SELECT 顺序需与此保持一致）
_SYNC_LOG_COLUMNS = (
    "id", "sync_type", "trigger_by", "status", "start_time", "end_time",
    "elapsed_seconds", "rows_synced", "error_message",
)


def _row_to_status(row: Any) -> Dict[str, Any]:
    """将 dws_sync_log 一行转换为状态 dict（时间字段转为字符串）。"""
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


def get_sync_status() -> Dict[str, Any]:
    """返回最近一次同步的状态；无记录时返回 no_sync_found。"""
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
    return _row_to_status(row)


def get_sync_history(limit: int = 10) -> Dict[str, Any]:
    """返回同步历史记录（按时间倒序，最多 limit 条）与总条数。"""
    engine = get_etl_engine()
    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM dws_sync_log")).fetchone()[0]
        rows = conn.execute(
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
        ).fetchall()
    records = [_row_to_status(row) for row in rows]
    return {"total": total, "records": records}
