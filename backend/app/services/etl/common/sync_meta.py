"""ETL 共享底层模块（common/sync_meta.py）。

本文件从原 etl_sync.py 抽取，SQL 与调用语义保持不变，仅供 full_sync / incremental_sync 通过 `from app.services.etl.common import *` 复用。"""

from __future__ import annotations

import logging
from datetime import datetime
from sqlalchemy import text

from app.services.etl.common.db import (
    get_etl_engine, _exec, _exec_query, _table_count_approx)
from app.services.etl.common.constants import _ODS_TABLES
from app.services.etl.common.watermark import ODS_INCREMENTAL_CONFIG

logger = logging.getLogger(__name__)



# 以下函数/常量由原 etl_sync.py 抽取，SQL 与调用语义保持不变
def _update_sync_meta(total_rows: int) -> None:
    """Update dws_sync_meta for all ODS source tables."""
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    for tbl in _ODS_TABLES:
        cnt = _table_count_approx(tbl)
        if tbl in ODS_INCREMENTAL_CONFIG:
            # 已配置表的水位（时间/ID）由 _set_watermark_after_load 维护，
            # 这里只刷新运行时间与行数，避免用 now 覆盖真实水位。
            _exec(
                "INSERT INTO dws_sync_meta "
                "  (table_name, last_sync_time, last_run_time, rows_synced, status) "
                "VALUES (:tbl, '1970-01-01 00:00:00', :ts, :cnt, 'success') "
                "ON DUPLICATE KEY UPDATE "
                "  last_run_time = VALUES(last_run_time), "
                "  rows_synced   = VALUES(rows_synced), "
                "  status        = 'success'",
                {"tbl": tbl, "ts": now_str, "cnt": cnt},
            )
        else:
            _exec(
                "INSERT INTO dws_sync_meta "
                "  (table_name, last_sync_time, last_run_time, rows_synced, status) "
                "VALUES (:tbl, :ts, :ts, :cnt, 'success') "
                "ON DUPLICATE KEY UPDATE "
                "  last_sync_time = VALUES(last_sync_time), "
                "  last_run_time  = VALUES(last_run_time), "
                "  rows_synced    = VALUES(rows_synced), "
                "  status         = 'success'",
                {"tbl": tbl, "ts": now_str, "cnt": cnt},
            )

    logger.info("Sync metadata updated for %d tables", len(_ODS_TABLES))


def _create_sync_log(sync_type: str, trigger_by: str) -> int:
    """Create a sync log entry, return the log ID."""
    engine = get_etl_engine()
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "INSERT INTO dws_sync_log "
                "  (sync_type, trigger_by, status, start_time) "
                "VALUES (:sync_type, :trigger_by, 'running', NOW())"
            ),
            {"sync_type": sync_type, "trigger_by": trigger_by},
        )
        return result.lastrowid


def _update_sync_log(
    log_id: int,
    status: str,
    rows_synced: int = 0,
    error_message: str = "",
    details: dict | None = None,
) -> None:
    """Update a sync log entry."""
    import json
    engine = get_etl_engine()
    with engine.begin() as conn:
        if details is not None:
            try:
                details_json = json.dumps(details, ensure_ascii=False)
            except Exception as e:
                logger.error("Failed to serialize details to JSON: %s", e)
                details_json = json.dumps({"error": "Failed to serialize details"})
        else:
            details_json = None
        
        conn.execute(
            text(
                "UPDATE dws_sync_log SET "
                "  status = :status, "
                "  end_time = NOW(), "
                "  rows_synced = :rows_synced, "
                "  error_message = :error_message, "
                "  details = :details "
                "WHERE id = :log_id"
            ),
            {
                "log_id": log_id,
                "status": status,
                "rows_synced": rows_synced,
                "error_message": error_message,
                "details": details_json,
            },
        )


def _calculate_accurate_rows_synced(cm_stats: Dict, ix_stats: Dict, batch_id: int) -> int:
    """Calculate accurate rows_synced by querying the actual tables.
    
    Instead of relying on MySQL rowcount (which can be inaccurate for
    ON DUPLICATE KEY UPDATE), we count the actual records with the
    current sync_batch_id.
    
    Note: After table rotation, the new data is in the main tables,
    so we query the main tables to get accurate count.
    """
    engine = get_etl_engine()
    total = 0
    
    # Count contact_mapping records with this batch_id
    # After rotation, new data is in main table
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT COUNT(*) FROM dws_contact_mapping "
                "WHERE sync_batch_id = :batch_id"
            ),
            {"batch_id": batch_id}
        )
        cm_count = result.fetchone()[0]
        
        total += cm_count
        logger.info("  Accurate count: dws_contact_mapping %d records (batch_id=%d)", 
                    cm_count, batch_id)
    
    # Count interaction_detail records with this batch_id
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT COUNT(*) FROM dws_interaction_detail "
                "WHERE sync_batch_id = :batch_id"
            ),
            {"batch_id": batch_id}
        )
        ix_count = result.fetchone()[0]
        
        total += ix_count
        logger.info("  Accurate count: dws_interaction_detail %d records (batch_id=%d)", 
                    ix_count, batch_id)
    
    logger.info("  Total accurate rows_synced: %d", total)
    return total


def _get_accurate_stats_by_source(table: str, batch_id: int) -> Dict[str, int]:
    """按 source_table 分组精确统计实际影响行数。
    
    通过查询 sync_batch_id 来精确统计，避免 MySQL rowcount 不准确的问题。
    MySQL rowcount 对于 ON DUPLICATE KEY UPDATE：插入=1，更新=2，无变化=0。
    
    Args:
        table: 表名（dws_contact_mapping 或 dws_interaction_detail）
        batch_id: 当前同步批次 ID
        
    Returns:
        按 source_table 分组的统计结果，如 {"zhique": 10, "crm": 20}
    """
    engine = get_etl_engine()
    
    # 确定 source_table 字段名（dws_interaction_detail 使用 channel 或需要根据实际情况调整）
    source_field = "source_table"
    
    # Determine which table to query - use temp table for incremental sync
    # After table rotation, new data will be in main table, but this function
    # is called before rotation, so we need to check both possibilities
    tables_to_check = [table, f"{table}_temp"]
    
    stats_by_source = {}
    with engine.connect() as conn:
        for check_table in tables_to_check:
            result = conn.execute(
                text(
                    f"SELECT {source_field}, COUNT(*) as cnt "
                    f"FROM {check_table} "
                    "WHERE sync_batch_id = :batch_id "
                    f"GROUP BY {source_field}"
                ),
                {"batch_id": batch_id}
            )
            for row in result.fetchall():
                if row[0]:  # 忽略 source_table 为 NULL 的记录
                    stats_by_source[row[0]] = stats_by_source.get(row[0], 0) + row[1]
    
    logger.info("  Accurate stats for %s (batch_id=%d): %s", table, batch_id, stats_by_source)
    return stats_by_source
