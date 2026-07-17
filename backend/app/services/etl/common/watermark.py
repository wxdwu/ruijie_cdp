"""ETL 共享底层模块（common/watermark.py）。

本文件从原 etl_sync.py 抽取，SQL 与调用语义保持不变，仅供 full_sync / incremental_sync 通过 `from app.services.etl.common import *` 复用。"""

from __future__ import annotations

import logging
from datetime import datetime
from sqlalchemy import text

from app.services.etl.common.db import get_etl_engine, _exec, _exec_query

logger = logging.getLogger(__name__)



# 以下函数/常量由原 etl_sync.py 抽取，SQL 与调用语义保持不变
def _ensure_sync_batch_column(table: str) -> None:
    """Check if sync_batch_id column exists, add if not."""
    rows = _exec_query(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = 'app_cdp' "
        "  AND table_name = :t AND column_name = 'sync_batch_id' "
        "LIMIT 1",
        {"t": table},
    )
    if not rows:
        logger.info("Adding sync_batch_id column to %s", table)
        _exec(
            f"ALTER TABLE {table} "
            "ADD COLUMN sync_batch_id BIGINT DEFAULT 0 "
            "COMMENT '同步批次ID，用于增量同步删除检测'"
        )


def _ensure_attribute_column(table: str) -> None:
    """Check if attribute column exists on dws_customer_360* tables, add if not."""
    # First verify the table actually exists (it may have been renamed away by table rotation)
    table_rows = _exec_query(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'app_cdp' "
        "  AND table_name = :t "
        "LIMIT 1",
        {"t": table},
    )
    if not table_rows:
        return

    rows = _exec_query(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = 'app_cdp' "
        "  AND table_name = :t AND column_name = 'attribute' "
        "LIMIT 1",
        {"t": table},
    )
    if not rows:
        logger.info("Adding attribute column to %s", table)
        _exec(
            f"ALTER TABLE {table} "
            "ADD COLUMN attribute VARCHAR(4) DEFAULT NULL "
            "COMMENT '客户分级 H/M/L/空'"
        )


def ensure_schema_for_incremental() -> None:
    """Ensure all DWS tables have the required fields for incremental sync."""
    tables = [
        "dws_contact_mapping",
        "dws_interaction_detail",
        "dws_customer_360",
        "dws_contact_360",
    ]
    for tbl in tables:
        _ensure_sync_batch_column(tbl)
    
    # Ensure attribute column on dws_customer_360 and its mirror tables
    for tbl in ("dws_customer_360", "dws_customer_360_temp", "dws_customer_360_backup"):
        _ensure_attribute_column(tbl)

    # 确保 ID 类字段水位列存在
    _ensure_watermark_column()

    logger.info("Schema check for incremental sync completed")


def _get_sync_batch_id() -> int:
    """Generate a new sync batch ID (Unix timestamp in milliseconds)."""
    return int(datetime.now().timestamp() * 1000)


def _get_last_sync_time(table_name: str) -> datetime | None:
    """Get the last successful sync time for a given ODS table.
    
    Returns:
        datetime object or None if no previous sync
    """
    rows = _exec_query(
        "SELECT last_sync_time FROM dws_sync_meta "
        "WHERE table_name = :tbl AND status = 'success' "
        "ORDER BY last_sync_time DESC LIMIT 1",
        {"tbl": table_name},
    )
    if rows and rows[0][0]:
        return rows[0][0]
    return None


ODS_INCREMENTAL_CONFIG: Dict[str, Dict[str, Any]] = {
    "ods_zhique_behavior_list_day":      {"mode": "incremental", "field": "behavior_time",   "field_type": "time"},
    "ods_linkflow_contacts_day":         {"mode": "incremental", "field": "contact_id",      "field_type": "id"},
    "ods_linkflow_events_day":           {"mode": "incremental", "field": "extra_id",        "field_type": "id"},
    "ods_tianrun_session_day":           {"mode": "incremental", "field": "start_time_sec",  "field_type": "unix_time"},
    # 以下为全量或暂未接入增量路径的表，仅记录便于后续扩展：
    "ods_tianrun_customer_profile_day":    {"mode": "full"},
    "ods_crm_opportunity_data_day":        {"mode": "full"},
    "ods_crm_lead_data_day":               {"mode": "full"},
    "ods_crm_key_account_output_list_day": {"mode": "full"},
    "ods_tianrun_session_detail_day":      {"mode": "incremental", "field": "start_time_sec", "field_type": "unix_time"},
    "ods_ruijie_website_user_day":         {"mode": "incremental", "field": "register_time",  "field_type": "time"},
}


def _get_last_watermark_id(table_name: str):
    """获取 ID 类字段表的上一轮最大 id 水位（dws_sync_meta.last_watermark_value）。"""
    rows = _exec_query(
        "SELECT last_watermark_value FROM dws_sync_meta "
        "WHERE table_name = :tbl AND status = 'success' "
        "ORDER BY last_run_time DESC LIMIT 1",
        {"tbl": table_name},
    )
    if rows and rows[0][0] is not None:
        return int(rows[0][0])
    return None


def _ensure_watermark_column() -> None:
    """幂等为 dws_sync_meta 增加 last_watermark_value 列（存储 ID 类字段最大 id 水位）。"""
    engine = get_etl_engine()
    with engine.connect() as conn:
        exists = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = 'app_cdp' "
                "  AND table_name = 'dws_sync_meta' "
                "  AND column_name = 'last_watermark_value' "
                "LIMIT 1"
            )
        ).fetchone()
    if not exists:
        _exec(
            "ALTER TABLE dws_sync_meta "
            "ADD COLUMN last_watermark_value BIGINT NOT NULL DEFAULT 0 "
            "COMMENT 'ID 类字段增量同步的水位：上次同步到的最大 id'"
        )
        logger.info("已为 dws_sync_meta 增加 last_watermark_value 列")


def _watermark_filter(table_name: str, alias: str):
    """返回增量过滤片段与水位值 (filter_clause, watermark_value)。

    - mode="full" 或 首次无水位 → ("", None)，调用方不加过滤（整表处理）
    - 否则返回 "AND <alias>.<field> > :watermark"（unix 时间用 FROM_UNIXTIME 包装）与水位值
    """
    cfg = ODS_INCREMENTAL_CONFIG.get(table_name)
    if cfg is None or cfg["mode"] == "full":
        return "", None

    if cfg["field_type"] == "id":
        wm = _get_last_watermark_id(table_name)
    else:
        wm = _get_last_sync_time(table_name)

    if wm is None:
        return "", None

    field = cfg["field"]
    if cfg["field_type"] == "unix_time":
        clause = f"AND FROM_UNIXTIME({alias}.{field}) > :watermark"
    else:
        clause = f"AND {alias}.{field} > :watermark"
    return clause, wm


def _set_watermark_after_load(table_name: str) -> None:
    """增量加载某表后，把当前最大水位写回 dws_sync_meta。

    时间字段 → last_sync_time（unix 时间存 FROM_UNIXTIME(MAX)）；ID 字段 → last_watermark_value。
    """
    cfg = ODS_INCREMENTAL_CONFIG.get(table_name)
    if cfg is None or cfg["mode"] == "full":
        return
    field = cfg["field"]
    if cfg["field_type"] == "id":
        _exec(
            "INSERT INTO dws_sync_meta "
            "  (table_name, last_watermark_value, last_sync_time, last_run_time, status) "
            "VALUES (:tbl, (SELECT COALESCE(MAX(" + field + "), 0) FROM " + table_name + "), '1970-01-01 00:00:00', NOW(), 'success') "
            "ON DUPLICATE KEY UPDATE "
            "  last_watermark_value = VALUES(last_watermark_value), "
            "  last_sync_time = VALUES(last_sync_time), "
            "  last_run_time = NOW(), status = 'success'",
            {"tbl": table_name},
        )
    else:
        max_expr = f"FROM_UNIXTIME(MAX({field}))" if cfg["field_type"] == "unix_time" else f"MAX({field})"
        _exec(
            "INSERT INTO dws_sync_meta "
            "  (table_name, last_sync_time, last_run_time, status) "
            "VALUES (:tbl, (SELECT COALESCE(" + max_expr + ", '1970-01-01 00:00:00') FROM " + table_name + "), NOW(), 'success') "
            "ON DUPLICATE KEY UPDATE "
            "  last_sync_time = VALUES(last_sync_time), "
            "  last_run_time = NOW(), status = 'success'",
            {"tbl": table_name},
        )
