"""
ETL Sync V2 – ODS → DWS 全量和增量同步服务.

在原有 etl_sync.py 基础上新增：
1. 全量同步（同原逻辑，增加 trigger_by 和日志记录到 dws_sync_log）
2. 增量同步（UPSERT + 删除检测 + 缺失数据恢复）
3. 同步日志记录到 dws_sync_log 表

增量同步核心策略：
- 使用 ON DUPLICATE KEY UPDATE 处理新增和更新
- 使用 sync_batch_id 标记记录，检测被删除的数据
- 保留已有数据，只同步变更部分
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.config import settings

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Database engine
# ─────────────────────────────────────────────────────────────────────────────

_engine: Engine | None = None


def get_etl_engine() -> Engine:
    """Return (or create) a dedicated SQLAlchemy engine for ETL work."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.DATABASE_URL,
            pool_size=5,
            max_overflow=10,
            pool_recycle=1800,
            pool_pre_ping=True,
            echo=False,
        )
    return _engine


# ─────────────────────────────────────────────────────────────────────────────
# Utility helpers
# ─────────────────────────────────────────────────────────────────────────────

def _exec(sql: str, params: dict | None = None) -> int:
    """Execute a SQL statement and return rowcount."""
    engine = get_etl_engine()
    with engine.begin() as conn:
        result = conn.execute(text(sql), params or {})
        return result.rowcount


def _exec_query(sql: str, params: dict | None = None):
    """Execute a SQL query and return all rows."""
    engine = get_etl_engine()
    with engine.connect() as conn:
        return conn.execute(text(sql), params or {}).fetchall()


def _table_count(table: str) -> int:
    rows = _exec_query(f"SELECT COUNT(*) FROM {table}")
    return rows[0][0] if rows else 0


def _get_sync_batch_id() -> int:
    """Generate a new sync batch ID (Unix timestamp in milliseconds)."""
    return int(datetime.now().timestamp() * 1000)


# ─────────────────────────────────────────────────────────────────────────────
# Schema migration – 确保 DWS 表有 sync_batch_id 字段
# ─────────────────────────────────────────────────────────────────────────────

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
    logger.info("Schema check for incremental sync completed")


# ─────────────────────────────────────────────────────────────────────────────
# Sync log helpers
# ─────────────────────────────────────────────────────────────────────────────

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
        # 正确处理 details 参数，确保 dict 被转换为 JSON 字符串
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


# ─────────────────────────────────────────────────────────────────────────────
# Full Sync Logic (same as original etl_sync.py, with logging)
# ─────────────────────────────────────────────────────────────────────────────

BATCH_SIZE = 10_000

ROLE_MAP: Dict[str, str] = {
    "拍板者": "决策者",
    "决策者": "决策者",
    "评估者": "技术评估者",
    "使用者": "使用者",
    "其他": "其他",
    "未知": "未知",
}

ZHIQUE_CHANNEL_MAP: Dict[str, str] = {
    "打开邮件": "email",
    "点击邮件链接": "email",
    "报名会议": "event",
    "参会": "event",
    "观看直播": "event",
    "下载资料": "web",
    "单页面表单提交": "web",
    "访问落地页": "web",
}


def _ensure_index(table: str, index_name: str, columns: str) -> None:
    """Create an index if it does not already exist."""
    rows = _exec_query(
        "SELECT 1 FROM information_schema.statistics "
        "WHERE table_schema = 'app_cdp' "
        "  AND table_name = :t AND index_name = :idx LIMIT 1",
        {"t": table, "idx": index_name},
    )
    if not rows:
        logger.info("Creating index %s on %s(%s)", index_name, table, columns)
        _exec(f"CREATE INDEX {index_name} ON {table} ({columns})")


def _create_indexes() -> None:
    """Create indexes needed for efficient joins during ETL."""
    _ensure_index("dws_contact_mapping", "idx_cm_mobile", "mobile")
    _ensure_index("dws_contact_mapping", "idx_cm_custname", "customer_name")
    _ensure_index("ods_crm_contact_day", "idx_crm_mobile", "mobile")
    _ensure_index("ods_linkflow_contacts_day", "idx_lf_cid", "contact_id")
    _ensure_index("ods_linkflow_events_day", "idx_lfe_cid", "contact_id")
    _ensure_index("ods_zhique_behavior_list_day", "idx_zqb_mobile", "mobile_phone")
    _ensure_index("ods_tianrun_session_day", "idx_tr_vid", "visitor_id")


def _full_load_contact_mapping() -> Dict[str, int]:
    """Full load: TRUNCATE + INSERT into dws_contact_mapping."""
    stats: Dict[str, int] = {}
    logger.info("Full sync: Truncating dws_contact_mapping...")
    _exec("TRUNCATE TABLE dws_contact_mapping")

    # Zhique contacts
    n = _exec(
        "INSERT IGNORE INTO dws_contact_mapping "
        "  (customer_name, contact_name, mobile, email, department, "
        "   position, source_table, etl_time) "
        "SELECT "
        "  z.related_company, z.contact_name, z.mobile, z.email, z.department, "
        "  z.position, "
        "  'zhique', NOW() "
        "FROM ods_zhique_contact_day z "
        "WHERE z.related_company IS NOT NULL AND z.related_company != ''"
    )
    stats["zhique"] = n
    logger.info("  [zhique] %d rows", n)

    # CRM contacts
    role_case = " ".join(
        f"WHEN c.purchase_role = '{k}' THEN '{v}'"
        for k, v in ROLE_MAP.items()
    )
    n = _exec(
        "INSERT IGNORE INTO dws_contact_mapping "
        "  (customer_name, contact_name, mobile, email, department, "
        "   position, purchase_role, role_category, source_table, etl_time) "
        "SELECT "
        "  c.customer_name, c.contact_name, c.mobile, c.email, c.department, "
        "  c.position, c.purchase_role, "
        f"  CASE {role_case} ELSE '未知' END, "
        "  'crm', NOW() "
        "FROM ods_crm_contact_day c "
        "WHERE c.customer_name IS NOT NULL AND c.customer_name != '' "
        "  AND ( c.customer_name IN (SELECT related_company FROM ods_zhique_contact_day) "
        "     OR c.mobile IN (SELECT mobile FROM ods_zhique_contact_day WHERE mobile IS NOT NULL) )"
    )
    stats["crm"] = n
    logger.info("  [crm] %d rows", n)

    # Marketing leads
    n = _exec(
        "INSERT IGNORE INTO dws_contact_mapping "
        "  (customer_name, contact_name, mobile, email, "
        "   position, source_table, etl_time) "
        "SELECT DISTINCT "
        "  COALESCE(m.final_company_name, m.customer_company, m.opp_customer_name), "
        "  m.customer_name, m.contact_phone, m.email, "
        "  m.lead_function, 'marketing', NOW() "
        "FROM ods_marketing_lead_day m "
        "WHERE COALESCE(m.final_company_name, m.customer_company, m.opp_customer_name) "
        "      IS NOT NULL "
        "  AND COALESCE(m.final_company_name, m.customer_company, m.opp_customer_name) "
        "      != ''"
    )
    stats["marketing"] = n
    logger.info("  [marketing] %d rows", n)

    # Linkflow contacts
    n = _exec(
        "INSERT IGNORE INTO dws_contact_mapping "
        "  (customer_name, contact_name, mobile, email, "
        "   linkflow_contact_id, source_table, etl_time) "
        "SELECT "
        "  crm.customer_name, l.name, l.mobile_phone, l.email, "
        "  l.contact_id, 'linkflow', NOW() "
        "FROM ods_linkflow_contacts_day l "
        "INNER JOIN ods_crm_contact_day crm "
        "  ON crm.mobile COLLATE utf8mb4_0900_ai_ci "
        "   = l.mobile_phone COLLATE utf8mb4_0900_ai_ci "
        "WHERE l.mobile_phone IS NOT NULL AND l.mobile_phone != '' "
        "  AND crm.customer_name IS NOT NULL AND crm.customer_name != ''"
    )
    stats["linkflow"] = n
    logger.info("  [linkflow] %d rows", n)

    # Tianrun contacts
    n = _exec(
        "INSERT IGNORE INTO dws_contact_mapping "
        "  (customer_name, contact_name, source_table, etl_time) "
        "SELECT DISTINCT "
        "  s.customer_name, s.visitor_name, 'tianrun', NOW() "
        "FROM ods_tianrun_session_day s "
        "WHERE s.customer_name IS NOT NULL AND s.customer_name != '' "
        "  AND s.visitor_name IS NOT NULL AND s.visitor_name != ''"
    )
    stats["tianrun"] = n
    logger.info("  [tianrun] %d rows", n)

    total = sum(stats.values())
    logger.info("Full sync: contact mapping complete, %d total rows", total)
    return stats


def _full_load_interaction_detail() -> Dict[str, int]:
    """Full load: TRUNCATE + INSERT into dws_interaction_detail."""
    stats: Dict[str, int] = {}
    logger.info("Full sync: Truncating dws_interaction_detail...")
    _exec("TRUNCATE TABLE dws_interaction_detail")

    # Zhique behaviors
    stats["zhique"] = _load_interactions_zhique()
    # Tianrun sessions
    stats["tianrun"] = _load_interactions_tianrun()
    # Linkflow events
    stats["linkflow"] = _load_interactions_linkflow()

    total = sum(stats.values())
    logger.info("Full sync: interaction detail complete, %d total rows", total)
    return stats


def _load_interactions_zhique() -> int:
    """Load Zhique behaviors → dws_interaction_detail."""
    channel_case = " ".join(
        f"WHEN b.behavior_type = '{k}' THEN '{v}'"
        for k, v in ZHIQUE_CHANNEL_MAP.items()
    )
    channel_case = f"CASE {channel_case} ELSE 'other' END"

    total_rows = _table_count("ods_zhique_behavior_list_day")
    logger.info("  Loading %d Zhique behaviors...", total_rows)

    engine = get_etl_engine()
    inserted = 0
    offset = 0

    while True:
        sql = text(
            "INSERT IGNORE INTO dws_interaction_detail "
            "  (customer_name, contact_name, mobile, source_table, "
            "   channel, behavior_type, content, event_time, source_id, etl_time) "
            "SELECT "
            "  cm.customer_name, b.contact_name, b.mobile_phone, 'zhique', "
            f"  {channel_case}, b.behavior_type, b.behavior_name, "
            "  b.behavior_time, b.behavior_id, NOW() "
            "FROM ods_zhique_behavior_list_day b "
            "INNER JOIN ods_crm_contact_day cm "
            "  ON cm.mobile COLLATE utf8mb4_0900_ai_ci "
            "   = b.mobile_phone COLLATE utf8mb4_0900_ai_ci "
            "  AND cm.customer_name IS NOT NULL AND cm.customer_name != '' "
            "WHERE b.id > :offset "
            "ORDER BY b.id "
            f"LIMIT {BATCH_SIZE}"
        )
        with engine.begin() as conn:
            result = conn.execute(sql, {"offset": offset})
            n = result.rowcount

        if n == 0:
            break
        inserted += n
        rows = _exec_query(
            "SELECT MAX(id) FROM ods_zhique_behavior_list_day WHERE id > :offset",
            {"offset": offset},
        )
        offset = rows[0][0] if rows and rows[0][0] else offset + BATCH_SIZE
        logger.info("    Zhique: %d / ~%d rows", inserted, total_rows)

    logger.info("  Zhique behaviors → interaction_detail: %d rows", inserted)
    return inserted


def _load_interactions_tianrun() -> int:
    """Load Tianrun sessions → dws_interaction_detail."""
    total_rows = _table_count("ods_tianrun_session_day")
    logger.info("  Loading %d Tianrun sessions...", total_rows)

    engine = get_etl_engine()
    inserted = 0
    offset = 0

    while True:
        sql = text(
            "INSERT IGNORE INTO dws_interaction_detail "
            "  (customer_name, contact_name, source_table, channel, "
            "   behavior_type, content, event_time, "
            "   is_high_value, source_id, etl_time) "
            "SELECT "
            "  s.customer_name, "
            "  s.visitor_name, 'tianrun', "
            "  CASE s.contact_type_name "
            "    WHEN '网页' THEN 'web' "
            "    WHEN '企微客服' THEN 'wechat' "
            "    WHEN '百度营销' THEN 'web' "
            "    ELSE 'web' "
            "  END, "
            "  COALESCE(s.receive_type_name, 'online_chat'), "
            "  COALESCE(s.close_reason_name, ''), "
            "  FROM_UNIXTIME(s.start_time_sec), "
            "  CASE WHEN s.total_duration > 60 THEN 1 ELSE 0 END, "
            "  s.id, NOW() "
            "FROM ods_tianrun_session_day s "
            "WHERE s.id > :offset "
            "  AND s.customer_name IS NOT NULL AND s.customer_name != '' "
            "ORDER BY s.id "
            f"LIMIT {BATCH_SIZE}"
        )
        with engine.begin() as conn:
            result = conn.execute(sql, {"offset": offset})
            n = result.rowcount

        if n == 0:
            break
        inserted += n
        rows = _exec_query(
            "SELECT MAX(id) FROM ods_tianrun_session_day WHERE id > :offset",
            {"offset": offset},
        )
        offset = rows[0][0] if rows and rows[0][0] else offset + BATCH_SIZE
        logger.info("    Tianrun: %d / ~%d rows", inserted, total_rows)

    logger.info("  Tianrun sessions → interaction_detail: %d rows", inserted)
    return inserted


def _load_interactions_linkflow() -> int:
    """Load Linkflow events → dws_interaction_detail."""
    total_rows = _table_count("ods_linkflow_events_day")
    logger.info("  Loading %d Linkflow events...", total_rows)

    engine = get_etl_engine()
    inserted = 0
    offset = 0

    while True:
        sql = text(
            "INSERT IGNORE INTO dws_interaction_detail "
            "  (customer_name, contact_name, mobile, source_table, "
            "   channel, behavior_type, event_time, source_id, etl_time) "
            "SELECT "
            "  crm.customer_name, lc.name, lc.mobile_phone, 'linkflow', "
            "  'web', e.event_name, "
            "  FROM_UNIXTIME(e.event_date_ms / 1000), "
            "  e.event_id, NOW() "
            "FROM ods_linkflow_events_day e "
            "INNER JOIN ods_linkflow_contacts_day lc ON lc.contact_id = e.contact_id "
            "INNER JOIN ods_crm_contact_day crm "
            "  ON crm.mobile COLLATE utf8mb4_0900_ai_ci "
            "   = lc.mobile_phone COLLATE utf8mb4_0900_ai_ci "
            "WHERE e.id > :offset "
            "  AND lc.mobile_phone IS NOT NULL AND lc.mobile_phone != '' "
            "  AND crm.customer_name IS NOT NULL AND crm.customer_name != '' "
            "ORDER BY e.id "
            f"LIMIT {BATCH_SIZE}"
        )
        with engine.begin() as conn:
            result = conn.execute(sql, {"offset": offset})
            n = result.rowcount

        if n == 0:
            break
        inserted += n
        rows = _exec_query(
            "SELECT MAX(id) FROM ods_linkflow_events_day WHERE id > :offset",
            {"offset": offset},
        )
        offset = rows[0][0] if rows and rows[0][0] else offset + BATCH_SIZE
        if inserted % (BATCH_SIZE * 10) < BATCH_SIZE:
            logger.info("    Linkflow: %d / ~%d rows", inserted, total_rows)

    logger.info("  Linkflow events → interaction_detail: %d rows", inserted)
    return inserted


def _full_build_customer_360() -> int:
    """Full build: TRUNCATE + INSERT into dws_customer_360."""
    logger.info("Full sync: Truncating dws_customer_360...")
    _exec("TRUNCATE TABLE dws_customer_360")

    # Phase 1: Interaction aggregates
    logger.info("Phase 1: Computing interaction aggregates...")
    n = _exec(
        "INSERT INTO dws_customer_360 ( "
        "  customer_name, interaction_count_total, interaction_count_30d, "
        "  last_interaction_time, last_interaction_channel, "
        "  top_channels, updated_at "
        ") "
        "SELECT "
        "  icp.customer_name, "
        "  COALESCE(COUNT(i.id), 0) AS interaction_count_total, "
        "  COALESCE(SUM(CASE WHEN i.event_time >= DATE_SUB(NOW(), INTERVAL 30 DAY) "
        "      THEN 1 ELSE 0 END), 0) AS interaction_count_30d, "
        "  MAX(i.event_time) AS last_interaction_time, "
        "  SUBSTRING_INDEX( "
        "    GROUP_CONCAT(DISTINCT i.channel ORDER BY i.channel SEPARATOR ','), "
        "    ',', 1 "
        "  ) AS last_interaction_channel, "
        "  IFNULL(CAST( "
        "    CONCAT('[', GROUP_CONCAT(DISTINCT CONCAT('\"', i.channel, '\"')), ']') "
        "    AS JSON "
        "  ), '[]') AS top_channels, "
        "  NOW() "
        "FROM tmp_icp_customers icp "
        "LEFT JOIN dws_interaction_detail i ON i.customer_name COLLATE utf8mb4_0900_ai_ci = icp.customer_name COLLATE utf8mb4_0900_ai_ci "
        "GROUP BY icp.customer_name "
        "ON DUPLICATE KEY UPDATE "
        "  interaction_count_total   = VALUES(interaction_count_total), "
        "  interaction_count_30d     = VALUES(interaction_count_30d), "
        "  last_interaction_time     = VALUES(last_interaction_time), "
        "  last_interaction_channel  = VALUES(last_interaction_channel), "
        "  top_channels              = VALUES(top_channels), "
        "  updated_at                = NOW()"
    )
    logger.info("Phase 1 done: %d customer rows", n)

    # Phase 2: CRM contact attributes
    logger.info("Phase 2: Enriching with CRM contact attributes...")
    n = _exec(
        "UPDATE dws_customer_360 c360 "
        "INNER JOIN ( "
        "  SELECT "
        "    customer_name, "
        "    MAX(industry) AS industry, "
        "    MAX(ruijie_region) AS region, "
        "    MAX(sales_name) AS owner_name, "
        "    COUNT(DISTINCT contact_name) AS contact_count, "
        "    COUNT(DISTINCT CASE WHEN mobile IS NOT NULL AND mobile != '' "
        "        THEN mobile END) AS mobile_count "
        "  FROM ods_crm_contact_day "
        "  GROUP BY customer_name "
        ") crm ON crm.customer_name COLLATE utf8mb4_0900_ai_ci "
        "     = c360.customer_name COLLATE utf8mb4_0900_ai_ci "
        "SET "
        "  c360.industry       = COALESCE(crm.industry, c360.industry), "
        "  c360.region         = COALESCE(crm.region, c360.region), "
        "  c360.owner_name     = COALESCE(crm.owner_name, c360.owner_name), "
        "  c360.contact_count  = crm.contact_count, "
        "  c360.mobile_count   = crm.mobile_count"
    )
    logger.info("Phase 2 done: %d rows enriched", n)

    # Phase 3: CRM opportunity metrics
    logger.info("Phase 3: Enriching with CRM opportunity metrics...")
    n = _exec(
        "UPDATE dws_customer_360 c360 "
        "INNER JOIN ( "
        "  SELECT "
        "    customer_name, "
        "    MAX(customer_stage) AS purchase_stage, "
        "    MAX(forecast_type) AS forecast_type, "
        "    COUNT(CASE WHEN is_active = 1 THEN 1 END) AS active_opp_count, "
        "    COALESCE(SUM(CASE WHEN is_active = 1 "
        "        THEN amount_10k * 10000 ELSE 0 END), 0) AS active_opp_amount, "
        "    COUNT(CASE WHEN is_funnel = '是' THEN 1 END) AS funnel_opp_count, "
        "    COALESCE(SUM(actual_order_amount_10k * 10000), 0) AS won_amount "
        "  FROM ods_crm_opportunity_day "
        "  GROUP BY customer_name "
        ") opp ON opp.customer_name COLLATE utf8mb4_0900_ai_ci "
        "     = c360.customer_name COLLATE utf8mb4_0900_ai_ci "
        "SET "
        "  c360.purchase_stage    = opp.purchase_stage, "
        "  c360.forecast_type     = opp.forecast_type, "
        "  c360.active_opp_count  = opp.active_opp_count, "
        "  c360.active_opp_amount = opp.active_opp_amount, "
        "  c360.funnel_opp_count  = opp.funnel_opp_count, "
        "  c360.won_amount        = opp.won_amount"
    )
    logger.info("Phase 3 done: %d rows enriched", n)

    # Phase 4: Derived fields
    logger.info("Phase 4: Computing derived fields...")
    _exec(
        "UPDATE dws_customer_360 c360 "
        "INNER JOIN ( "
        "  SELECT customer_name, "
        "    CASE "
        "      WHEN COUNT(DISTINCT CASE WHEN role_category = '决策者' THEN 1 END) > 0 "
        "       AND COUNT(DISTINCT CASE WHEN role_category = '技术评估者' THEN 1 END) > 0 "
        "       AND COUNT(DISTINCT CASE WHEN role_category = '使用者' THEN 1 END) > 0 "
        "      THEN '全' "
        "      WHEN COUNT(DISTINCT role_category) > 0 THEN '部分' "
        "      ELSE '无' "
        "    END AS role_coverage "
        "  FROM dws_contact_mapping "
        "  GROUP BY customer_name "
        ") rm ON rm.customer_name = c360.customer_name "
        "SET c360.role_coverage = rm.role_coverage"
    )
    _exec(
        "UPDATE dws_customer_360 c360 "
        "INNER JOIN ( "
        "  SELECT customer_name, "
        "    CAST(CONCAT('[', GROUP_CONCAT(DISTINCT "
        "      CONCAT('\"', source_table, '\"') "
        "    ), ']') AS JSON) AS source_tables "
        "  FROM dws_contact_mapping "
        "  GROUP BY customer_name "
        ") st ON st.customer_name = c360.customer_name "
        "SET c360.source_tables = st.source_tables"
    )
    _exec(
        "UPDATE dws_customer_360 c360 "
        "SET "
        "  c360.data_coverage = JSON_OBJECT( "
        "    'has_crm',      c360.industry IS NOT NULL, "
        "    'has_opp',      c360.active_opp_count > 0, "
        "    'has_contacts', c360.contact_count > 0, "
        "    'has_interactions', c360.interaction_count_total > 0 "
        "  ), "
        "  c360.intent_score = "
        "    LEAST(100, "
        "      c360.interaction_count_30d * 2 "
        "      + IF(c360.active_opp_count > 0, 20, 0) "
        "      + IF(c360.contact_count >= 3, 10, c360.contact_count * 3) "
        "    ), "
        "  c360.intent_level = CASE "
        "    WHEN c360.interaction_count_30d >= 10 "
        "         AND c360.active_opp_count > 0 THEN '高' "
        "    WHEN c360.interaction_count_30d >= 3 THEN '中' "
        "    WHEN c360.interaction_count_total > 0 THEN '低' "
        "    ELSE '无' "
        "  END"
    )

    total = _table_count("dws_customer_360")
    logger.info("Full sync: customer 360 complete, %d rows", total)
    return total


def _full_build_contact_360() -> int:
    """Full build: TRUNCATE + INSERT into dws_contact_360."""
    logger.info("Full sync: Truncating dws_contact_360...")
    _exec("TRUNCATE TABLE dws_contact_360")

    n = _exec(
        "INSERT IGNORE INTO dws_contact_360 ( "
        "  customer_id, contact_name, mobile, email, department, position, "
        "  purchase_role, role_category, interaction_count, interaction_count_30d, "
        "  last_interaction_time, source_tables, linkflow_contact_id, updated_at "
        ") "
        "SELECT "
        "  c360.id AS customer_id, "
        "  cm.contact_name, cm.mobile, cm.email, cm.department, cm.position, "
        "  cm.purchase_role, cm.role_category, "
        "  COALESCE(agg.interaction_count, 0), "
        "  COALESCE(agg.interaction_count_30d, 0), "
        "  agg.last_interaction_time, "
        "  CAST(CONCAT('[\"', cm.source_table, '\"]') AS JSON), "
        "  cm.linkflow_contact_id, "
        "  NOW() "
        "FROM dws_contact_mapping cm "
        "LEFT JOIN dws_customer_360 c360 ON c360.customer_name = cm.customer_name "
        "LEFT JOIN ( "
        "  SELECT contact_name, mobile, "
        "    COUNT(*) AS interaction_count, "
        "    SUM(CASE WHEN event_time >= DATE_SUB(NOW(), INTERVAL 30 DAY) "
        "        THEN 1 ELSE 0 END) AS interaction_count_30d, "
        "    MAX(event_time) AS last_interaction_time "
        "  FROM dws_interaction_detail "
        "  WHERE contact_name IS NOT NULL "
        "  GROUP BY contact_name, mobile "
        ") agg ON (agg.contact_name = cm.contact_name "
        "          AND agg.mobile <=> cm.mobile) "
        "ON DUPLICATE KEY UPDATE "
        "  interaction_count     = VALUES(interaction_count), "
        "  interaction_count_30d = VALUES(interaction_count_30d), "
        "  last_interaction_time = VALUES(last_interaction_time), "
        "  updated_at            = NOW()"
    )

    _exec(
        "UPDATE dws_contact_360 SET "
        "  activity_level = CASE "
        "    WHEN interaction_count_30d >= 10 THEN 'high' "
        "    WHEN interaction_count_30d >= 3 THEN 'medium' "
        "    WHEN interaction_count > 0 THEN 'low' "
        "    ELSE 'none' "
        "  END"
    )

    total = _table_count("dws_contact_360")
    logger.info("Full sync: contact 360 complete, %d rows", total)
    return total


def _update_sync_meta(total_rows: int) -> None:
    """Update dws_sync_meta for all ODS source tables."""
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    ods_tables = [
        "ods_crm_contact_day",
        "ods_crm_opportunity_day",
        "ods_zhique_contact_day",
        "ods_marketing_lead_day",
        "ods_zhique_behavior_list_day",
        "ods_tianrun_session_day",
        "ods_linkflow_contacts_day",
        "ods_linkflow_events_day",
        "ods_ruijie_website_user_day",
        "ods_tianrun_customer_profile_day",
    ]

    for tbl in ods_tables:
        cnt = _table_count(tbl)
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

    logger.info("Sync metadata updated for %d tables", len(ods_tables))


# ─────────────────────────────────────────────────────────────────────────────
# Incremental Sync Logic
# ─────────────────────────────────────────────────────────────────────────────

def _incremental_upsert_contact_mapping(batch_id: int) -> Dict[str, int]:
    """Incremental UPSERT into dws_contact_mapping.
    
    Uses ON DUPLICATE KEY UPDATE to handle inserts and updates.
    Marks synced records with the current batch_id.
    """
    stats: Dict[str, int] = {}
    
    # For incremental sync, we UPSERT from each ODS source
    # Strategy: 
    # 1. INSERT ... ON DUPLICATE KEY UPDATE for each source
    # 2. Update sync_batch_id for processed records
    
    logger.info("Incremental sync: UPSERT dws_contact_mapping...")
    
    # Zhique contacts - UPSERT
    n = _exec(
        "INSERT INTO dws_contact_mapping "
        "  (customer_name, contact_name, mobile, email, department, "
        "   position, source_table, etl_time, sync_batch_id) "
        "SELECT "
        "  z.related_company, z.contact_name, z.mobile, z.email, z.department, "
        "  z.position, "
        "  'zhique', NOW(), :batch_id "
        "FROM ods_zhique_contact_day z "
        "WHERE z.related_company IS NOT NULL AND z.related_company != '' "
        "ON DUPLICATE KEY UPDATE "
        "  contact_name = VALUES(contact_name), "
        "  email = VALUES(email), "
        "  department = VALUES(department), "
        "  position = VALUES(position), "
        "  etl_time = VALUES(etl_time), "
        "  sync_batch_id = VALUES(sync_batch_id)",
        {"batch_id": batch_id},
    )
    stats["zhique"] = n
    
    # For other sources, similar UPSERT logic
    # CRM contacts
    role_case = " ".join(
        f"WHEN c.purchase_role = '{k}' THEN '{v}'"
        for k, v in ROLE_MAP.items()
    )
    n = _exec(
        "INSERT INTO dws_contact_mapping "
        "  (customer_name, contact_name, mobile, email, department, "
        "   position, purchase_role, role_category, source_table, etl_time, sync_batch_id) "
        "SELECT "
        "  c.customer_name, c.contact_name, c.mobile, c.email, c.department, "
        "  c.position, c.purchase_role, "
        f"  CASE {role_case} ELSE '未知' END, "
        "  'crm', NOW(), :batch_id "
        "FROM ods_crm_contact_day c "
        "WHERE c.customer_name IS NOT NULL AND c.customer_name != '' "
        "  AND ( c.customer_name IN (SELECT related_company FROM ods_zhique_contact_day) "
        "     OR c.mobile IN (SELECT mobile FROM ods_zhique_contact_day WHERE mobile IS NOT NULL) ) "
        "ON DUPLICATE KEY UPDATE "
        "  contact_name = VALUES(contact_name), "
        "  email = VALUES(email), "
        "  purchase_role = VALUES(purchase_role), "
        "  role_category = VALUES(role_category), "
        "  etl_time = VALUES(etl_time), "
        "  sync_batch_id = VALUES(sync_batch_id)",
        {"batch_id": batch_id},
    )
    stats["crm"] = n
    
    # Marketing leads
    n = _exec(
        "INSERT INTO dws_contact_mapping "
        "  (customer_name, contact_name, mobile, email, "
        "   position, source_table, etl_time, sync_batch_id) "
        "SELECT DISTINCT "
        "  COALESCE(m.final_company_name, m.customer_company, m.opp_customer_name), "
        "  m.customer_name, m.contact_phone, m.email, "
        "  m.lead_function, 'marketing', NOW(), :batch_id "
        "FROM ods_marketing_lead_day m "
        "WHERE COALESCE(m.final_company_name, m.customer_company, m.opp_customer_name) "
        "      IS NOT NULL "
        "  AND COALESCE(m.final_company_name, m.customer_company, m.opp_customer_name) "
        "      != '' "
        "ON DUPLICATE KEY UPDATE "
        "  contact_name = VALUES(contact_name), "
        "  email = VALUES(email), "
        "  position = VALUES(position), "
        "  etl_time = VALUES(etl_time), "
        "  sync_batch_id = VALUES(sync_batch_id)",
        {"batch_id": batch_id},
    )
    stats["marketing"] = n
    
    # Linkflow contacts
    n = _exec(
        "INSERT INTO dws_contact_mapping "
        "  (customer_name, contact_name, mobile, email, "
        "   linkflow_contact_id, source_table, etl_time, sync_batch_id) "
        "SELECT "
        "  crm.customer_name, l.name, l.mobile_phone, l.email, "
        "  l.contact_id, 'linkflow', NOW(), :batch_id "
        "FROM ods_linkflow_contacts_day l "
        "INNER JOIN ods_crm_contact_day crm "
        "  ON crm.mobile COLLATE utf8mb4_0900_ai_ci "
        "   = l.mobile_phone COLLATE utf8mb4_0900_ai_ci "
        "WHERE l.mobile_phone IS NOT NULL AND l.mobile_phone != '' "
        "  AND crm.customer_name IS NOT NULL AND crm.customer_name != '' "
        "ON DUPLICATE KEY UPDATE "
        "  contact_name = VALUES(contact_name), "
        "  email = VALUES(email), "
        "  linkflow_contact_id = VALUES(linkflow_contact_id), "
        "  etl_time = VALUES(etl_time), "
        "  sync_batch_id = VALUES(sync_batch_id)",
        {"batch_id": batch_id},
    )
    stats["linkflow"] = n
    
    # Tianrun contacts
    n = _exec(
        "INSERT INTO dws_contact_mapping "
        "  (customer_name, contact_name, source_table, etl_time, sync_batch_id) "
        "SELECT DISTINCT "
        "  s.customer_name, s.visitor_name, 'tianrun', NOW(), :batch_id "
        "FROM ods_tianrun_session_day s "
        "WHERE s.customer_name IS NOT NULL AND s.customer_name != '' "
        "  AND s.visitor_name IS NOT NULL AND s.visitor_name != '' "
        "ON DUPLICATE KEY UPDATE "
        "  etl_time = VALUES(etl_time), "
        "  sync_batch_id = VALUES(sync_batch_id)",
        {"batch_id": batch_id},
    )
    stats["tianrun"] = n
    
    # Delete records that are no longer in ODS (sync_batch_id != current batch_id)
    deleted = _exec(
        "DELETE FROM dws_contact_mapping "
        "WHERE sync_batch_id != :batch_id AND sync_batch_id != 0",
        {"batch_id": batch_id},
    )
    stats["deleted"] = deleted
    if deleted > 0:
        logger.info("  Deleted %d stale contact mapping records", deleted)
    
    logger.info("Incremental sync: contact mapping done, stats=%s", stats)
    return stats


def _incremental_upsert_interaction_detail(batch_id: int) -> Dict[str, int]:
    """Incremental UPSERT into dws_interaction_detail."""
    stats: Dict[str, int] = {}
    
    logger.info("Incremental sync: UPSERT dws_interaction_detail...")
    
    # For interaction detail, we use source_table + source_id as unique key
    # Strategy: UPSERT new/updated interactions, mark with batch_id
    
    # Zhique behaviors - UPSERT
    channel_case = " ".join(
        f"WHEN b.behavior_type = '{k}' THEN '{v}'"
        for k, v in ZHIQUE_CHANNEL_MAP.items()
    )
    channel_case = f"CASE {channel_case} ELSE 'other' END"
    
    # Use INSERT ... ON DUPLICATE KEY UPDATE for incremental sync
    # First, get max behavior_id already synced
    rows = _exec_query(
        "SELECT MAX(CAST(source_id AS UNSIGNED)) FROM dws_interaction_detail "
        "WHERE source_table = 'zhique'"
    )
    max_synced_id = rows[0][0] if rows and rows[0][0] else 0
    
    logger.info("  Zhique: max synced behavior_id = %s", max_synced_id)
    
    # Insert new Zhique behaviors (id > max_synced_id)
    engine = get_etl_engine()
    inserted = 0
    offset = max_synced_id
    
    while True:
        sql = text(
            "INSERT IGNORE INTO dws_interaction_detail "
            "  (customer_name, contact_name, mobile, source_table, "
            "   channel, behavior_type, content, event_time, source_id, etl_time, sync_batch_id) "
            "SELECT "
            "  cm.customer_name, b.contact_name, b.mobile_phone, 'zhique', "
            f"  {channel_case}, b.behavior_type, b.behavior_name, "
            "  b.behavior_time, b.behavior_id, NOW(), :batch_id "
            "FROM ods_zhique_behavior_list_day b "
            "INNER JOIN ods_crm_contact_day cm "
            "  ON cm.mobile COLLATE utf8mb4_0900_ai_ci "
            "   = b.mobile_phone COLLATE utf8mb4_0900_ai_ci "
            "  AND cm.customer_name IS NOT NULL AND cm.customer_name != '' "
            "WHERE b.id > :offset "
            "ORDER BY b.id "
            f"LIMIT {BATCH_SIZE}"
        )
        with engine.begin() as conn:
            result = conn.execute(sql, {"offset": offset, "batch_id": batch_id})
            n = result.rowcount
        
        if n == 0:
            break
        inserted += n
        rows = _exec_query(
            "SELECT MAX(id) FROM ods_zhique_behavior_list_day WHERE id > :offset",
            {"offset": offset},
        )
        offset = rows[0][0] if rows and rows[0][0] else offset + BATCH_SIZE
    
    stats["zhique"] = inserted
    logger.info("  Zhique: %d new interactions", inserted)
    
    # Update sync_batch_id for existing interactions (mark as still valid)
    _exec(
        "UPDATE dws_interaction_detail SET sync_batch_id = :batch_id "
        "WHERE source_table = 'zhique' AND sync_batch_id != :batch_id",
        {"batch_id": batch_id},
    )
    
    # For Tianrun and Linkflow, similar logic
    # Tianrun sessions
    stats["tianrun"] = _incremental_load_tianrun(batch_id)
    stats["linkflow"] = _incremental_load_linkflow(batch_id)
    
    logger.info("Incremental sync: interaction detail done, stats=%s", stats)
    return stats


def _incremental_load_tianrun(batch_id: int) -> int:
    """Incrementally load new Tianrun sessions."""
    rows = _exec_query(
        "SELECT MAX(CAST(source_id AS UNSIGNED)) FROM dws_interaction_detail "
        "WHERE source_table = 'tianrun'"
    )
    max_synced_id = rows[0][0] if rows and rows[0][0] else 0
    
    engine = get_etl_engine()
    inserted = 0
    offset = max_synced_id
    
    while True:
        sql = text(
            "INSERT IGNORE INTO dws_interaction_detail "
            "  (customer_name, contact_name, source_table, channel, "
            "   behavior_type, content, event_time, "
            "   is_high_value, source_id, etl_time, sync_batch_id) "
            "SELECT "
            "  s.customer_name, "
            "  s.visitor_name, 'tianrun', "
            "  CASE s.contact_type_name "
            "    WHEN '网页' THEN 'web' "
            "    WHEN '企微客服' THEN 'wechat' "
            "    WHEN '百度营销' THEN 'web' "
            "    ELSE 'web' "
            "  END, "
            "  COALESCE(s.receive_type_name, 'online_chat'), "
            "  COALESCE(s.close_reason_name, ''), "
            "  FROM_UNIXTIME(s.start_time_sec), "
            "  CASE WHEN s.total_duration > 60 THEN 1 ELSE 0 END, "
            "  s.id, NOW(), :batch_id "
            "FROM ods_tianrun_session_day s "
            "WHERE s.id > :offset "
            "  AND s.customer_name IS NOT NULL AND s.customer_name != '' "
            "ORDER BY s.id "
            f"LIMIT {BATCH_SIZE}"
        )
        with engine.begin() as conn:
            result = conn.execute(sql, {"offset": offset, "batch_id": batch_id})
            n = result.rowcount
        
        if n == 0:
            break
        inserted += n
        rows = _exec_query(
            "SELECT MAX(id) FROM ods_tianrun_session_day WHERE id > :offset",
            {"offset": offset},
        )
        offset = rows[0][0] if rows and rows[0][0] else offset + BATCH_SIZE
    
    logger.info("  Tianrun: %d new interactions", inserted)
    return inserted


def _incremental_load_linkflow(batch_id: int) -> int:
    """Incrementally load new Linkflow events."""
    rows = _exec_query(
        "SELECT MAX(CAST(source_id AS UNSIGNED)) FROM dws_interaction_detail "
        "WHERE source_table = 'linkflow'"
    )
    max_synced_id = rows[0][0] if rows and rows[0][0] else 0
    
    engine = get_etl_engine()
    inserted = 0
    offset = max_synced_id
    
    while True:
        sql = text(
            "INSERT IGNORE INTO dws_interaction_detail "
            "  (customer_name, contact_name, mobile, source_table, "
            "   channel, behavior_type, event_time, source_id, etl_time, sync_batch_id) "
            "SELECT "
            "  crm.customer_name, lc.name, lc.mobile_phone, 'linkflow', "
            "  'web', e.event_name, "
            "  FROM_UNIXTIME(e.event_date_ms / 1000), "
            "  e.event_id, NOW(), :batch_id "
            "FROM ods_linkflow_events_day e "
            "INNER JOIN ods_linkflow_contacts_day lc ON lc.contact_id = e.contact_id "
            "INNER JOIN ods_crm_contact_day crm "
            "  ON crm.mobile COLLATE utf8mb4_0900_ai_ci "
            "   = lc.mobile_phone COLLATE utf8mb4_0900_ai_ci "
            "WHERE e.id > :offset "
            "  AND lc.mobile_phone IS NOT NULL AND lc.mobile_phone != '' "
            "  AND crm.customer_name IS NOT NULL AND crm.customer_name != '' "
            "ORDER BY e.id "
            f"LIMIT {BATCH_SIZE}"
        )
        with engine.begin() as conn:
            result = conn.execute(sql, {"offset": offset, "batch_id": batch_id})
            n = result.rowcount
        
        if n == 0:
            break
        inserted += n
        rows = _exec_query(
            "SELECT MAX(id) FROM ods_linkflow_events_day WHERE id > :offset",
            {"offset": offset},
        )
        offset = rows[0][0] if rows and rows[0][0] else offset + BATCH_SIZE
    
    logger.info("  Linkflow: %d new interactions", inserted)
    return inserted


def _incremental_rebuild_aggregates(batch_id: int) -> Dict[str, int]:
    """Rebuild customer_360 and contact_360 for affected customers.
    
    In incremental mode, we only rebuild aggregates for customers
    that have new/updated interactions or contacts.
    For simplicity, we do a full rebuild of the aggregate tables
    (they are not that large).
    """
    logger.info("Incremental sync: Rebuilding aggregate tables...")
    
    # Rebuild customer_360 (full rebuild for simplicity)
    c360_count = _full_build_customer_360()
    
    # Rebuild contact_360
    ct360_count = _full_build_contact_360()
    
    return {"customer_360": c360_count, "contact_360": ct360_count}


# ─────────────────────────────────────────────────────────────────────────────
# Main ETL orchestrators
# ─────────────────────────────────────────────────────────────────────────────

def run_full_sync(trigger_by: str = "system") -> Dict[str, Any]:
    """Execute full ETL sync with logging to dws_sync_log.
    
    Same logic as original run_etl(), but with logging.
    """
    log_id = _create_sync_log("full", trigger_by)
    logger.info("Full sync started, log_id=%d, trigger_by=%s", log_id, trigger_by)
    
    start_time = datetime.now()
    stats: Dict[str, Any] = {
        "start_time": start_time.isoformat(),
        "steps": {},
        "status": "running",
        "log_id": log_id,
    }
    
    try:
        # Ensure schema
        ensure_schema_for_incremental()
        
        # Step 0: Indexes
        logger.info("── Step 0: Creating indexes ──")
        _create_indexes()
        stats["steps"]["indexes"] = "created"
        
        # Step 1: Contact mapping
        logger.info("── Step 1: Loading contact mapping (full) ──")
        cm_stats = _full_load_contact_mapping()
        stats["steps"]["contact_mapping"] = cm_stats
        
        # Step 2: Interaction detail
        logger.info("── Step 2: Loading interaction detail (full) ──")
        ix_stats = _full_load_interaction_detail()
        stats["steps"]["interaction_detail"] = ix_stats
        
        # Step 3: Customer 360
        logger.info("── Step 3: Building customer-360 ──")
        c360_count = _full_build_customer_360()
        stats["steps"]["customer_360"] = {"rows": c360_count}
        
        # Step 4: Contact 360
        logger.info("── Step 4: Building contact-360 ──")
        ct360_count = _full_build_contact_360()
        stats["steps"]["contact_360"] = {"rows": ct360_count}
        
        # Step 5: Sync metadata
        logger.info("── Step 5: Updating sync metadata ──")
        total_interaction_rows = sum(ix_stats.values())
        _update_sync_meta(total_interaction_rows)
        stats["steps"]["sync_meta"] = "updated"
        
        # Done
        elapsed = (datetime.now() - start_time).total_seconds()
        stats.update({
            "status": "success",
            "end_time": datetime.now().isoformat(),
            "elapsed_seconds": round(elapsed, 2),
        })
        
        # Update sync log
        _update_sync_log(
            log_id=log_id,
            status="success",
            rows_synced=sum(cm_stats.values()) + total_interaction_rows,
            details=stats["steps"],
        )
        
        logger.info("═══════════════════════════════════════════════════")
        logger.info(" Full sync completed in %.1f s", elapsed)
        logger.info("═══════════════════════════════════════════════════")
        return stats
        
    except Exception as exc:
        stats["status"] = "error"
        stats["error"] = str(exc)
        logger.exception("Full sync failed: %s", exc)
        
        _update_sync_log(
            log_id=log_id,
            status="failed",
            error_message=str(exc),
            details=stats.get("steps"),
        )
        raise


def run_incremental_sync(trigger_by: str = "system") -> Dict[str, Any]:
    """Execute incremental ETL sync with logging to dws_sync_log.
    
    Handles insert/update/delete scenarios:
    1. UPSERT new/updated records from ODS
    2. Detect and delete records that no longer exist in ODS
    3. Rebuild aggregate tables
    """
    log_id = _create_sync_log("incremental", trigger_by)
    logger.info("Incremental sync started, log_id=%d, trigger_by=%s", log_id, trigger_by)
    
    start_time = datetime.now()
    batch_id = _get_sync_batch_id()
    logger.info("Sync batch_id = %d", batch_id)
    
    stats: Dict[str, Any] = {
        "start_time": start_time.isoformat(),
        "batch_id": batch_id,
        "steps": {},
        "status": "running",
        "log_id": log_id,
    }
    
    try:
        # Ensure schema
        ensure_schema_for_incremental()
        
        # Step 0: Indexes
        logger.info("── Step 0: Creating indexes ──")
        _create_indexes()
        stats["steps"]["indexes"] = "created"
        
        # Step 1: UPSERT contact mapping
        logger.info("── Step 1: UPSERT contact mapping (incremental) ──")
        cm_stats = _incremental_upsert_contact_mapping(batch_id)
        stats["steps"]["contact_mapping"] = cm_stats
        
        # Step 2: UPSERT interaction detail
        logger.info("── Step 2: UPSERT interaction detail (incremental) ──")
        ix_stats = _incremental_upsert_interaction_detail(batch_id)
        stats["steps"]["interaction_detail"] = ix_stats
        
        # Step 3: Rebuild aggregates
        logger.info("── Step 3: Rebuilding aggregates ──")
        agg_stats = _incremental_rebuild_aggregates(batch_id)
        stats["steps"]["aggregates"] = agg_stats
        
        # Step 4: Sync metadata
        logger.info("── Step 4: Updating sync metadata ──")
        total_rows = sum(cm_stats.get(k, 0) for k in cm_stats if k != "deleted")
        total_rows += sum(ix_stats.values())
        _update_sync_meta(total_rows)
        stats["steps"]["sync_meta"] = "updated"
        
        # Done
        elapsed = (datetime.now() - start_time).total_seconds()
        stats.update({
            "status": "success",
            "end_time": datetime.now().isoformat(),
            "elapsed_seconds": round(elapsed, 2),
        })
        
        # Update sync log
        _update_sync_log(
            log_id=log_id,
            status="success",
            rows_synced=total_rows,
            details=stats["steps"],
        )
        
        logger.info("═══════════════════════════════════════════════════")
        logger.info(" Incremental sync completed in %.1f s", elapsed)
        logger.info("═══════════════════════════════════════════════════")
        return stats
        
    except Exception as exc:
        stats["status"] = "error"
        stats["error"] = str(exc)
        logger.exception("Incremental sync failed: %s", exc)
        
        _update_sync_log(
            log_id=log_id,
            status="failed",
            error_message=str(exc),
            details=stats.get("steps"),
        )
        raise
