"""
Incremental ETL sync – ODS → DWS layer.

Orchestrates loading from source ODS tables, transforming, and upserting
into the DWS interaction / customer-360 tables.

Target database: 192.168.159.22:33307/app_cdp  (same as app.config.settings)

Actual ODS tables (with _day suffix):
  ods_crm_contact_day, ods_crm_opportunity_day, ods_zhique_contact_day,
  ods_marketing_lead_day, ods_zhique_behavior_list_day, ods_tianrun_session_day,
  ods_linkflow_contacts_day, ods_linkflow_events_day,
  ods_ruijie_website_user_day, ods_tianrun_customer_profile_day,
  ods_tianrun_session_detail_day

DWS target tables:
  dws_contact_mapping, dws_interaction_detail,
  dws_customer_360, dws_contact_360, dws_sync_meta
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.config import settings

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Database config
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
# Constants
# ─────────────────────────────────────────────────────────────────────────────

BATCH_SIZE = 10_000

# CRM purchase_role → role_category mapping
ROLE_MAP: Dict[str, str] = {
    "拍板者": "决策者",
    "决策者": "决策者",
    "评估者": "技术评估者",
    "使用者": "使用者",
    "其他":   "其他",
    "未知":   "未知",
}

# Zhique behavior_type → channel
ZHIQUE_CHANNEL_MAP: Dict[str, str] = {
    "打开邮件":       "email",
    "点击邮件链接":   "email",
    "报名会议":       "event",
    "参会":           "event",
    "观看直播":       "event",
    "下载资料":       "web",
    "单页面表单提交": "web",
    "访问落地页":     "web",
}

# All linkflow events are website interactions
LINKFLOW_DEFAULT_CHANNEL = "web"


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


def _table_count(table: str) -> int:
    rows = _exec_query(f"SELECT COUNT(*) FROM {table}")
    return rows[0][0] if rows else 0


def _create_indexes() -> None:
    """Create indexes needed for efficient joins during ETL."""
    _ensure_index("dws_contact_mapping", "idx_cm_mobile", "mobile")
    _ensure_index("dws_contact_mapping", "idx_cm_custname", "customer_name")
    _ensure_index("ods_crm_contact_day", "idx_crm_mobile", "mobile")
    _ensure_index("ods_linkflow_contacts_day", "idx_lf_cid", "contact_id")
    _ensure_index("ods_linkflow_events_day", "idx_lfe_cid", "contact_id")
    _ensure_index("ods_zhique_behavior_list_day", "idx_zqb_mobile", "mobile_phone")
    _ensure_index("ods_tianrun_session_day", "idx_tr_vid", "visitor_id")
    
    # Indexes for incremental sync performance
    _ensure_index("dws_interaction_detail", "idx_id_sync_batch", "sync_batch_id")
    _ensure_index("dws_contact_mapping", "idx_cm_sync_batch", "sync_batch_id")
    _ensure_index("tmp_icp_customers", "idx_icp_custname", "customer_name")


def _build_icp_customers_table() -> int:
    """Build tmp_icp_customers table from ods_zhique_contact_day.
    
    This table serves as the anchor/基准 for all subsequent ETL steps.
    It contains distinct customer names from Zhique contacts (ICP customers).
    
    Returns:
        Number of ICP customers loaded.
    """
    logger.info("Building tmp_icp_customers table (ICP customer anchor)...")
    
    # Create table if not exists
    _exec("""
        CREATE TABLE IF NOT EXISTS tmp_icp_customers (
            customer_name VARCHAR(255) NOT NULL PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """)
    
    # Truncate and reload
    _exec("TRUNCATE TABLE tmp_icp_customers")
    
    n = _exec(
        "INSERT IGNORE INTO tmp_icp_customers (customer_name) "
        "SELECT DISTINCT related_company "
        "FROM ods_zhique_contact_day "
        "WHERE related_company IS NOT NULL AND related_company != ''"
    )
    
    total = _table_count("tmp_icp_customers")
    logger.info("tmp_icp_customers built: %d ICP customers", total)
    return total


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Contact Mapping
# ─────────────────────────────────────────────────────────────────────────────

def _load_contact_mapping() -> Dict[str, int]:
    """Populate dws_contact_mapping from all ODS contact sources.

    Uses DELETE + INSERT per source to avoid duplicates (no unique constraint
    beyond auto-increment PK).

    Returns dict of {source_name: row_count}.
    """
    stats: Dict[str, int] = {}

    # Full reload: truncate target tables first
    logger.info("Truncating dws_contact_mapping for full reload…")
    _exec("TRUNCATE TABLE dws_contact_mapping")

    # ── a. Zhique contacts first (BASE / anchor - 2.4K ICP customers) ────
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
    logger.info("[a] Zhique contacts (BASE): %d rows (anchor for ICP)", n)

    # ── b. CRM contacts — only those matching zhique by company or mobile ──
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
    logger.info("[b] CRM contacts (matched to zhique): %d rows", n)

    # ── b. Zhique contacts (2.4K rows) ──────────────────────────────────
    n = _exec(
        "INSERT IGNORE INTO dws_contact_mapping "
        "  (customer_name, contact_name, mobile, email, department, "
        "   position, source_table, etl_time) "
        "SELECT "
        "  z.related_company, z.contact_name, z.mobile, z.email, z.department, "
        "  z.position, 'zhique', NOW() "
        "FROM ods_zhique_contact_day z "
        "WHERE z.related_company IS NOT NULL AND z.related_company != ''"
    )
    stats["zhique"] = n
    logger.info("[b] Zhique contacts → contact_mapping: %d rows", n)

    # ── c. Marketing leads (36K rows, deduplicate by company+contact) ───
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
    logger.info("[c] Marketing leads → contact_mapping: %d rows", n)

    # ── d. Linkflow contacts (73K rows, company is NULL for all) ────────
    # Match linkflow contacts to CRM customers via mobile_phone
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
    logger.info("[d] Linkflow contacts → contact_mapping: %d rows", n)

    # ── e. Tianrun contacts from sessions (aggregated by visitor) ───────
    # Note: Tianrun sessions have NO mobile_phone.  customer_name field
    # contains channel labels (百度营销, 网页, 企微客服), not real company names.
    # We create contact_mapping entries using customer_name where available,
    # understanding these are low-quality matches.
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
    logger.info("[e] Tianrun contacts → contact_mapping: %d rows", n)

    total = sum(stats.values())
    logger.info(
        "Contact mapping complete: %d total rows  %s",
        total, stats,
    )
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# Step 2: Interaction Detail
# ─────────────────────────────────────────────────────────────────────────────

def _build_zhique_channel_case() -> str:
    """Build SQL CASE expression for Zhique behavior_type → channel."""
    parts = " ".join(
        f"WHEN b.behavior_type = '{k}' THEN '{v}'"
        for k, v in ZHIQUE_CHANNEL_MAP.items()
    )
    return f"CASE {parts} ELSE 'other' END"


def _load_interactions_zhique() -> int:
    """Load Zhique behaviors (381K) → dws_interaction_detail.

    Match to customers via mobile_phone → CRM contacts.
    """
    channel_case = _build_zhique_channel_case()
    total_rows = _table_count("ods_zhique_behavior_list_day")
    logger.info(
        "  Loading %d Zhique behaviors (batch size %d)…",
        total_rows, BATCH_SIZE,
    )

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
        # Get max id processed
        rows = _exec_query(
            "SELECT MAX(id) FROM ods_zhique_behavior_list_day "
            "WHERE id > :offset",
            {"offset": offset},
        )
        offset = rows[0][0] if rows and rows[0][0] else offset + BATCH_SIZE
        logger.info("    Zhique: %d / ~%d rows", inserted, total_rows)

    logger.info("  Zhique behaviors → interaction_detail: %d rows", inserted)
    return inserted


def _load_interactions_tianrun() -> int:
    """Load Tianrun sessions (897K) → dws_interaction_detail.

    Tianrun sessions are online customer-service chats.  The visitor_mobile_phone
    is NULL for all rows.  We use visitor_id as the contact identifier and
    the contact_type_name as the channel source.  Customer names are channel
    labels rather than real company names, so we keep them for traceability.
    """
    total_rows = _table_count("ods_tianrun_session_day")
    logger.info(
        "  Loading %d Tianrun sessions (batch size %d)…",
        total_rows, BATCH_SIZE,
    )

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
    """Load Linkflow events (16.5M) → dws_interaction_detail.

    Events are linked to contacts via contact_id.  All events are web activity
    (page views, clicks, etc.) so channel is always 'web'.
    """
    total_rows = _table_count("ods_linkflow_events_day")
    logger.info(
        "  Loading %d Linkflow events (batch size %d)…",
        total_rows, BATCH_SIZE,
    )

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


def _load_interaction_detail() -> Dict[str, int]:
    """Load interactions from all sources into dws_interaction_detail.

    Returns dict of {source_name: row_count}.
    """
    logger.info("Truncating dws_interaction_detail for full reload…")
    _exec("TRUNCATE TABLE dws_interaction_detail")

    stats: Dict[str, int] = {}
    stats["zhique"] = _load_interactions_zhique()
    stats["tianrun"] = _load_interactions_tianrun()
    stats["linkflow"] = _load_interactions_linkflow()

    total = sum(stats.values())
    logger.info(
        "Interaction detail complete: %d total rows  %s",
        total, stats,
    )
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# Step 3: Customer 360 & Contact 360
# ─────────────────────────────────────────────────────────────────────────────

def _build_customer_360() -> int:
    """Build dws_customer_360 from interaction_detail, CRM opps, and contacts.

    Three-phase approach:
    1. INSERT interaction aggregates from dws_interaction_detail
    2. UPDATE with CRM opportunity metrics from ods_crm_opportunity_day
    3. UPDATE derived fields (role_coverage, data_coverage, source_tables)
    """
    logger.info("Truncating dws_customer_360 for full rebuild…")
    _exec("TRUNCATE TABLE dws_customer_360")

    logger.info("Phase 1: Computing interaction aggregates…")
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

    # ── Phase 2: Enrich with CRM contact attributes ─────────────────────
    logger.info("Phase 2: Enriching with CRM contact attributes…")
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

    # ── Phase 3: Enrich with CRM opportunity metrics ────────────────────
    logger.info("Phase 3: Enriching with CRM opportunity metrics…")
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

    # ── Phase 4: Derived fields ─────────────────────────────────────────
    logger.info("Phase 4: Computing derived fields…")

    # role_coverage
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

    # source_tables
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

    # data_coverage & intent scoring
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
    logger.info("Customer 360 complete: %d rows", total)
    return total


def _build_contact_360() -> int:
    """Build dws_contact_360 from contact_mapping and interaction_detail."""
    logger.info("Truncating dws_contact_360 for full rebuild…")
    _exec("TRUNCATE TABLE dws_contact_360")

    logger.info("Building contact-level 360 aggregates…")

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

    # Compute activity_level and lead_stage
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
    logger.info("Contact 360 complete: %d rows (affected %d)", total, n)
    return total


# ─────────────────────────────────────────────────────────────────────────────
# Step 4: Sync Metadata
# ─────────────────────────────────────────────────────────────────────────────

_ODS_TABLES = [
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


def _update_sync_meta(total_rows: int) -> None:
    """Update dws_sync_meta for all ODS source tables."""
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    for tbl in _ODS_TABLES:
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

    logger.info("Sync metadata updated for %d tables", len(_ODS_TABLES))


# ─────────────────────────────────────────────────────────────────────────────
# Main ETL orchestrator
# ─────────────────────────────────────────────────────────────────────────────

def run_etl() -> Dict[str, Any]:
    """Execute the full ETL pipeline.

    Steps:
    1. Create indexes for efficient joins
    2. Load contact mapping from all ODS sources
    3. Load interaction detail (zhique → tianrun → linkflow)
    4. Build customer-360 and contact-360 aggregates
    5. Update sync metadata

    Returns:
        Dict with step-level statistics and overall status.
    """
    start_time = datetime.now()
    logger.info("═══════════════════════════════════════════════════")
    logger.info(" ETL run started at %s", start_time.isoformat())
    logger.info("═══════════════════════════════════════════════════")

    stats: Dict[str, Any] = {
        "start_time": start_time.isoformat(),
        "steps": {},
        "status": "running",
    }

    try:
        # ── 0. Setup ────────────────────────────────────────────────────
        logger.info("── Step 0: Creating indexes ──")
        _create_indexes()
        stats["steps"]["indexes"] = "created"

        # ── 1. Contact mapping ──────────────────────────────────────────
        logger.info("── Step 1: Loading contact mapping ──")
        cm_stats = _load_contact_mapping()
        stats["steps"]["contact_mapping"] = cm_stats

        # ── 2. Interaction detail ───────────────────────────────────────
        logger.info("── Step 2: Loading interaction detail ──")
        ix_stats = _load_interaction_detail()
        stats["steps"]["interaction_detail"] = ix_stats

        # ── 3. Customer 360 & Contact 360 ───────────────────────────────
        logger.info("── Step 3: Building customer-360 ──")
        c360_count = _build_customer_360()
        stats["steps"]["customer_360"] = {"rows": c360_count}

        logger.info("── Step 4: Building contact-360 ──")
        ct360_count = _build_contact_360()
        stats["steps"]["contact_360"] = {"rows": ct360_count}

        # ── 4. Sync metadata ────────────────────────────────────────────
        logger.info("── Step 5: Updating sync metadata ──")
        total_interaction_rows = sum(ix_stats.values())
        _update_sync_meta(total_interaction_rows)
        stats["steps"]["sync_meta"] = "updated"

        # ── Done ────────────────────────────────────────────────────────
        elapsed = (datetime.now() - start_time).total_seconds()
        stats.update({
            "status": "success",
            "end_time": datetime.now().isoformat(),
            "elapsed_seconds": round(elapsed, 2),
        })

        logger.info("═══════════════════════════════════════════════════")
        logger.info(" ETL run completed in %.1f s", elapsed)
        logger.info("   Contact mapping:    %d rows", sum(cm_stats.values()))
        logger.info("   Interaction detail: %d rows", total_interaction_rows)
        logger.info("   Customer 360:       %d rows", c360_count)
        logger.info("   Contact 360:        %d rows", ct360_count)
        logger.info("═══════════════════════════════════════════════════")
        return stats

    except Exception as exc:
        stats["status"] = "error"
        stats["error"] = str(exc)
        logger.exception("ETL run failed: %s", exc)
        raise
"""
ETL Sync V2 Functions - Full Sync with Logging & Incremental Sync
Appended to etl_sync.py
"""

# ─────────────────────────────────────────────────────────────────────
# Schema migration – 确保 DWS 表有 sync_batch_id 字段
# ─────────────────────────────────────────────────────────────────────

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


def _count_table_rows(table: str, where_clause: str = "", params: dict | None = None) -> int:
    """Count rows in a table with optional WHERE clause."""
    sql = f"SELECT COUNT(*) FROM {table}"
    if where_clause:
        sql += f" WHERE {where_clause}"
    rows = _exec_query(sql, params)
    return rows[0][0] if rows else 0


# ─────────────────────────────────────────────────────────────────────
# Sync log helpers
# ─────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────
# Full Sync Logic (with logging)
# ─────────────────────────────────────────────────────────────────────

def run_full_sync(trigger_by: str = "system") -> Dict[str, Any]:
    """Execute full ETL sync with logging to dws_sync_log."""
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
        ensure_schema_for_incremental()
        
        logger.info("── Step 0: Building ICP customers table ──")
        icp_count = _build_icp_customers_table()
        stats["steps"]["icp_customers"] = {"rows": icp_count}
        
        logger.info("── Step 1: Creating indexes ──")
        _create_indexes()
        stats["steps"]["indexes"] = "created"
        
        logger.info("── Step 2: Loading contact mapping (full) ──")
        cm_stats = _load_contact_mapping()
        stats["steps"]["contact_mapping"] = cm_stats
        
        logger.info("── Step 3: Loading interaction detail (full) ──")
        ix_stats = _load_interaction_detail()
        stats["steps"]["interaction_detail"] = ix_stats
        
        logger.info("── Step 4: Building customer-360 ──")
        c360_count = _build_customer_360()
        stats["steps"]["customer_360"] = {"rows": c360_count}
        
        logger.info("── Step 5: Building contact-360 ──")
        ct360_count = _build_contact_360()
        stats["steps"]["contact_360"] = {"rows": ct360_count}
        
        logger.info("── Step 6: Updating sync metadata ──")
        total_interaction_rows = sum(ix_stats.values())
        _update_sync_meta(total_interaction_rows)
        stats["steps"]["sync_meta"] = "updated"
        
        elapsed = (datetime.now() - start_time).total_seconds()
        stats.update({
            "status": "success",
            "end_time": datetime.now().isoformat(),
            "elapsed_seconds": round(elapsed, 2),
        })
        
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


# ─────────────────────────────────────────────────────────────────────
# Incremental Sync Logic
# ─────────────────────────────────────────────────────────────────────

def run_incremental_sync(trigger_by: str = "system") -> Dict[str, Any]:
    """Execute incremental ETL sync with logging to dws_sync_log.
    
    Implements true incremental sync by only processing records
    where etl_time > last_sync_time.
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
        ensure_schema_for_incremental()
        
        logger.info("── Step 0: Creating indexes ──")
        _create_indexes()
        stats["steps"]["indexes"] = "created"
        
        logger.info("── Step 1: UPSERT contact mapping (true incremental) ──")
        cm_stats = _incremental_upsert_contact_mapping(batch_id)
        stats["steps"]["contact_mapping"] = cm_stats
        
        logger.info("── Step 2: UPSERT interaction detail (true incremental) ──")
        ix_stats = _incremental_upsert_interaction_detail(batch_id)
        stats["steps"]["interaction_detail"] = ix_stats
        
        # Only rebuild aggregates if new interactions were inserted
        total_new_interactions = sum(ix_stats.values())
        if total_new_interactions > 0:
            logger.info("── Step 3: Rebuilding aggregates (new data detected) ──")
            agg_stats = _incremental_rebuild_aggregates(batch_id)
            stats["steps"]["aggregates"] = agg_stats
        else:
            logger.info("── Step 3: Skipping aggregate rebuild (no new interactions) ──")
            stats["steps"]["aggregates"] = {"skipped": "no new data"}
        
        logger.info("── Step 4: Updating sync metadata ──")
        # Calculate actual rows_synced accurately
        # For incremental sync, rows_synced = sum of all affected records
        total_rows = sum(v for k, v in cm_stats.items() if k != "deleted")
        total_rows += sum(ix_stats.values())
        
        # Update sync metadata (which also updates last_sync_time)
        _update_sync_meta(total_rows)
        stats["steps"]["sync_meta"] = "updated"
        
        elapsed = (datetime.now() - start_time).total_seconds()
        stats.update({
            "status": "success",
            "end_time": datetime.now().isoformat(),
            "elapsed_seconds": round(elapsed, 2),
        })
        
        # Calculate accurate rows_synced
        # Note: MySQL rowcount for ON DUPLICATE KEY UPDATE returns:
        #   1 for insert, 2 for update, 0 for no change
        # We need to adjust for this to get accurate count
        accurate_rows_synced = _calculate_accurate_rows_synced(cm_stats, ix_stats, batch_id)
        
        _update_sync_log(
            log_id=log_id,
            status="success",
            rows_synced=accurate_rows_synced,
            details=stats["steps"],
        )
        
        logger.info("═══════════════════════════════════════════════════")
        logger.info(" Incremental sync completed in %.1f s", elapsed)
        logger.info(" Accurate rows_synced: %d", accurate_rows_synced)
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


def _calculate_accurate_rows_synced(cm_stats: Dict, ix_stats: Dict, batch_id: int) -> int:
    """Calculate accurate rows_synced by querying the actual tables.
    
    Instead of relying on MySQL rowcount (which can be inaccurate for
    ON DUPLICATE KEY UPDATE), we count the actual records with the
    current sync_batch_id.
    """
    engine = get_etl_engine()
    total = 0
    
    # Count contact_mapping records with this batch_id
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
    stats: Dict[str, int] = {}
    
    # 确定 source_table 字段名（dws_interaction_detail 使用 channel 或需要根据实际情况调整）
    source_field = "source_table"
    
    with engine.connect() as conn:
        result = conn.execute(
            text(
                f"SELECT {source_field}, COUNT(*) as cnt "
                f"FROM {table} "
                "WHERE sync_batch_id = :batch_id "
                f"GROUP BY {source_field}"
            ),
            {"batch_id": batch_id}
        )
        for row in result.fetchall():
            if row[0]:  # 忽略 source_table 为 NULL 的记录
                stats[row[0]] = row[1]
    
    logger.info("  Accurate stats for %s (batch_id=%d): %s", table, batch_id, stats)
    return stats


def _incremental_upsert_contact_mapping(batch_id: int) -> Dict[str, int]:
    """True incremental UPSERT into dws_contact_mapping.
    
    Only processes records where etl_time > last_sync_time.
    """
    stats: Dict[str, int] = {}
    
    logger.info("Incremental sync: UPSERT dws_contact_mapping (true incremental)...")
    
    # Get last sync time for each table
    last_sync_zhique = _get_last_sync_time("ods_zhique_contact_day")
    last_sync_crm = _get_last_sync_time("ods_crm_contact_day")
    last_sync_marketing = _get_last_sync_time("ods_marketing_lead_day")
    last_sync_linkflow = _get_last_sync_time("ods_linkflow_contacts_day")
    last_sync_tianrun = _get_last_sync_time("ods_tianrun_session_day")
    
    # Debug: log last sync times
    logger.info("Last sync times:")
    logger.info("  zhique: %s", last_sync_zhique)
    logger.info("  crm: %s", last_sync_crm)
    logger.info("  marketing: %s", last_sync_marketing)
    logger.info("  linkflow: %s", last_sync_linkflow)
    logger.info("  tianrun: %s", last_sync_tianrun)
    
    # Zhique contacts - only new/updated records
    zhique_filter = ""
    zhique_params = {"batch_id": batch_id}
    if last_sync_zhique:
        zhique_filter = "AND etl_time > :last_sync_time"
        zhique_params["last_sync_time"] = last_sync_zhique
        logger.info("  Zhique filter: etl_time > %s", last_sync_zhique)
    
    # Debug: check how many records match the filter
    debug_count = _count_table_rows(
        "ods_zhique_contact_day",
        f"related_company IS NOT NULL AND related_company != '' {zhique_filter}",
        zhique_params
    )
    logger.info("  Zhique: %d records match filter", debug_count)
    
    n = _exec(
        f"""
        INSERT INTO dws_contact_mapping 
          (customer_name, contact_name, mobile, email, department, 
           position, source_table, etl_time, sync_batch_id) 
        SELECT 
          z.related_company, z.contact_name, z.mobile, z.email, z.department, 
          z.position, 
          'zhique', NOW(), :batch_id 
        FROM ods_zhique_contact_day z 
        WHERE z.related_company IS NOT NULL AND z.related_company != '' 
          {zhique_filter}
        ON DUPLICATE KEY UPDATE 
          contact_name = VALUES(contact_name), 
          email = VALUES(email), 
          department = VALUES(department), 
          position = VALUES(position), 
          etl_time = VALUES(etl_time), 
          sync_batch_id = VALUES(sync_batch_id)
        """,
        zhique_params,
    )
    stats["zhique"] = n
    logger.info("  Zhique: %d records upserted (incremental), rowcount=%d", debug_count, n)
    
    # CRM contacts - only new/updated records
    crm_filter = ""
    crm_params = {"batch_id": batch_id}
    if last_sync_crm:
        crm_filter = "AND c.etl_time > :last_sync_time"
        crm_params["last_sync_time"] = last_sync_crm
    
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
        f" {crm_filter} "
        "ON DUPLICATE KEY UPDATE "
        "  contact_name = VALUES(contact_name), "
        "  email = VALUES(email), "
        "  purchase_role = VALUES(purchase_role), "
        "  role_category = VALUES(role_category), "
        "  etl_time = VALUES(etl_time), "
        "  sync_batch_id = VALUES(sync_batch_id)",
        crm_params,
    )
    stats["crm"] = n
    logger.info("  CRM: %d records upserted (incremental)", n)
    
    # Marketing leads - only new/updated records
    marketing_filter = ""
    marketing_params = {"batch_id": batch_id}
    if last_sync_marketing:
        marketing_filter = "AND m.etl_time > :last_sync_time"
        marketing_params["last_sync_time"] = last_sync_marketing
    
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
        f" {marketing_filter} "
        "ON DUPLICATE KEY UPDATE "
        "  contact_name = VALUES(contact_name), "
        "  email = VALUES(email), "
        "  position = VALUES(position), "
        "  etl_time = VALUES(etl_time), "
        "  sync_batch_id = VALUES(sync_batch_id)",
        marketing_params,
    )
    stats["marketing"] = n
    logger.info("  Marketing: %d records upserted (incremental)", n)
    
    # Linkflow contacts - only new/updated records
    linkflow_filter = ""
    linkflow_params = {"batch_id": batch_id}
    if last_sync_linkflow:
        linkflow_filter = "AND l.etl_time > :last_sync_time"
        linkflow_params["last_sync_time"] = last_sync_linkflow
    
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
        f" {linkflow_filter} "
        "ON DUPLICATE KEY UPDATE "
        "  contact_name = VALUES(contact_name), "
        "  email = VALUES(email), "
        "  linkflow_contact_id = VALUES(linkflow_contact_id), "
        "  etl_time = VALUES(etl_time), "
        "  sync_batch_id = VALUES(sync_batch_id)",
        linkflow_params,
    )
    stats["linkflow"] = n
    logger.info("  Linkflow: %d records upserted (incremental)", n)
    
    # Tianrun contacts - only new/updated records
    tianrun_filter = ""
    tianrun_params = {"batch_id": batch_id}
    if last_sync_tianrun:
        tianrun_filter = "AND s.etl_time > :last_sync_time"
        tianrun_params["last_sync_time"] = last_sync_tianrun
    
    n = _exec(
        "INSERT INTO dws_contact_mapping "
        "  (customer_name, contact_name, source_table, etl_time, sync_batch_id) "
        "SELECT DISTINCT "
        "  s.customer_name, s.visitor_name, 'tianrun', NOW(), :batch_id "
        "FROM ods_tianrun_session_day s "
        "WHERE s.customer_name IS NOT NULL AND s.customer_name != '' "
        "  AND s.visitor_name IS NOT NULL AND s.visitor_name != '' "
        f" {tianrun_filter} "
        "ON DUPLICATE KEY UPDATE "
        "  etl_time = VALUES(etl_time), "
        "  sync_batch_id = VALUES(sync_batch_id)",
        tianrun_params,
    )
    stats["tianrun"] = n
    logger.info("  Tianrun: %d records upserted (incremental)", n)
    
    # For incremental sync, we don't delete records (only add/update)
    # Delete detection can be implemented separately if needed
    stats["deleted"] = 0
    
    # 精确统计各数据源的实际影响行数（避免使用不准确的 rowcount）
    accurate_stats = _get_accurate_stats_by_source("dws_contact_mapping", batch_id)
    # 用精确统计的结果更新 stats
    for source, count in accurate_stats.items():
        stats[source] = count
    
    total_affected = sum(v for k, v in stats.items() if k != "deleted")
    logger.info("Incremental sync: contact mapping done, %d records affected", total_affected)
    return stats


def _incremental_upsert_interaction_detail(batch_id: int) -> Dict[str, int]:
    """True incremental UPSERT into dws_interaction_detail.
    
    Uses single INSERT IGNORE ... SELECT for optimal performance.
    Only processes ICP customer data (small dataset, no batching needed).
    """
    stats: Dict[str, int] = {}
    
    logger.info("Incremental sync: UPSERT dws_interaction_detail (true incremental)...")
    
    # Get last sync time for interaction tables
    last_sync_zhique = _get_last_sync_time("ods_zhique_behavior_list_day")
    last_sync_tianrun = _get_last_sync_time("ods_tianrun_session_day")
    last_sync_linkflow = _get_last_sync_time("ods_linkflow_events_day")
    
    # Zhique behaviors - single INSERT IGNORE ... SELECT
    channel_case = _build_zhique_channel_case()
    zhique_filter = ""
    zhique_params: Dict[str, Any] = {"batch_id": batch_id}
    
    if last_sync_zhique:
        zhique_filter = "AND b.behavior_time > :last_sync_time"
        zhique_params["last_sync_time"] = last_sync_zhique
        logger.info("  Zhique: filtering behaviors after %s", last_sync_zhique)
    
    engine = get_etl_engine()
    sql = text(
        "INSERT IGNORE INTO dws_interaction_detail "
        "  (customer_name, contact_name, mobile, source_table, "
        "   channel, behavior_type, content, event_time, source_id, etl_time, sync_batch_id) "
        "SELECT "
        "  cm.customer_name, b.contact_name, b.mobile_phone, 'zhique', "
        f"  {channel_case}, b.behavior_type, b.behavior_name, "
        "  b.behavior_time, b.id, NOW(), :batch_id "
        "FROM ods_zhique_behavior_list_day b "
        "INNER JOIN ods_crm_contact_day cm "
        "  ON cm.mobile COLLATE utf8mb4_0900_ai_ci "
        "   = b.mobile_phone COLLATE utf8mb4_0900_ai_ci "
        "WHERE cm.customer_name IS NOT NULL AND cm.customer_name != '' "
        f"  {zhique_filter}"
    )
    
    with engine.begin() as conn:
        result = conn.execute(sql, zhique_params)
        stats["zhique"] = result.rowcount
    
    logger.info("  Zhique: %d new interactions (incremental)", stats["zhique"])
    
    # Tianrun sessions - single INSERT IGNORE ... SELECT
    stats["tianrun"] = _incremental_load_tianrun(batch_id, last_sync_tianrun)
    
    # Linkflow events - single INSERT IGNORE ... SELECT
    stats["linkflow"] = _incremental_load_linkflow(batch_id, last_sync_linkflow)
    
    # 精确统计各数据源的实际影响行数（避免使用不准确的 rowcount）
    accurate_stats = _get_accurate_stats_by_source("dws_interaction_detail", batch_id)
    # 用精确统计的结果更新 stats
    for source, count in accurate_stats.items():
        stats[source] = count
    
    logger.info("Incremental sync: interaction detail done, stats=%s", stats)
    return stats


def _incremental_load_tianrun(batch_id: int, last_sync_time: datetime | None = None) -> int:
    """True incremental load of new Tianrun sessions.
    
    Uses single INSERT IGNORE ... SELECT for optimal performance.
    Only processes ICP customer data (small dataset, no batching needed).
    
    Args:
        batch_id: Current sync batch ID
        last_sync_time: Last successful sync time, if None process all
    """
    engine = get_etl_engine()
    
    # Build time filter - Tianrun uses start_time_sec (Unix timestamp)
    time_filter = ""
    params: Dict[str, Any] = {"batch_id": batch_id}
    
    if last_sync_time:
        # Convert datetime to Unix timestamp
        last_sync_timestamp = int(last_sync_time.timestamp())
        time_filter = "AND s.start_time_sec > :last_sync_timestamp"
        params["last_sync_timestamp"] = last_sync_timestamp
        logger.info("  Tianrun: filtering sessions after timestamp %d", last_sync_timestamp)
    
    # Single INSERT IGNORE ... SELECT (no batching needed for ICP customers)
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
        "WHERE s.customer_name IN (SELECT customer_name FROM tmp_icp_customers) "
        f" {time_filter} "
        "  AND s.customer_name IS NOT NULL AND s.customer_name != ''"
    )
    
    with engine.begin() as conn:
        result = conn.execute(sql, params)
        inserted = result.rowcount
    
    logger.info("  Tianrun: %d new interactions (incremental)", inserted)
    return inserted


def _incremental_load_linkflow(batch_id: int, last_sync_time: datetime | None = None) -> int:
    """True incremental load of new Linkflow events.
    
    Uses single INSERT IGNORE ... SELECT for optimal performance.
    Only processes ICP customer data (small dataset, no batching needed).
    
    Args:
        batch_id: Current sync batch ID
        last_sync_time: Last successful sync time, if None process all
    """
    engine = get_etl_engine()
    
    # Build time filter - Linkflow uses event_date_ms (Unix timestamp in milliseconds)
    time_filter = ""
    params: Dict[str, Any] = {"batch_id": batch_id}
    
    if last_sync_time:
        # Convert datetime to Unix timestamp in milliseconds
        last_sync_ms = int(last_sync_time.timestamp() * 1000)
        time_filter = "AND e.event_date_ms > :last_sync_ms"
        params["last_sync_ms"] = last_sync_ms
        logger.info("  Linkflow: filtering events after timestamp %d ms", last_sync_ms)
    
    # Single INSERT IGNORE ... SELECT (no batching needed for ICP customers)
    # 优化：增加ICP客户过滤，避免处理非ICP客户的数据
    sql = text(
        "INSERT IGNORE INTO dws_interaction_detail "
        "  (customer_name, contact_name, mobile, source_table, "
        "   channel, behavior_type, event_time, source_id, etl_time, sync_batch_id) "
        "SELECT "
        "  cm.customer_name, lc.name, lc.mobile_phone, 'linkflow', "
        "  'web', e.event_name, "
        "  FROM_UNIXTIME(e.event_date_ms / 1000), "
        "  e.event_id, NOW(), :batch_id "
        "FROM ods_linkflow_events_day e "
        "INNER JOIN ods_linkflow_contacts_day lc ON lc.contact_id = e.contact_id "
        "INNER JOIN dws_contact_mapping cm ON cm.mobile = lc.mobile_phone "
        "WHERE cm.customer_name IN (SELECT customer_name FROM tmp_icp_customers) "
        f" {time_filter} "
        "  AND lc.mobile_phone IS NOT NULL AND lc.mobile_phone != '' "
        "  AND cm.customer_name IS NOT NULL AND cm.customer_name != ''"
    )
    
    with engine.begin() as conn:
        result = conn.execute(sql, params)
        inserted = result.rowcount
    
    logger.info("  Linkflow: %d new interactions (incremental)", inserted)
    return inserted


def _get_affected_customers(batch_id: int) -> List[str]:
    """Get list of customer names affected by current sync batch.
    
    Customers are affected if they have new interactions in this batch
    or new contact mappings.
    """
    engine = get_etl_engine()
    customers = []
    
    # Get customers with new interactions
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT DISTINCT customer_name FROM dws_interaction_detail "
                "WHERE sync_batch_id = :batch_id AND customer_name IS NOT NULL"
            ),
            {"batch_id": batch_id}
        )
        customers.extend(row[0] for row in result.fetchall())
    
    # Get customers with new contact mappings
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT DISTINCT customer_name FROM dws_contact_mapping "
                "WHERE sync_batch_id = :batch_id AND customer_name IS NOT NULL"
            ),
            {"batch_id": batch_id}
        )
        customers.extend(row[0] for row in result.fetchall())
    
    # Remove duplicates
    return list(set(customers))


def _incremental_build_customer_360(batch_id: int) -> int:
    """Incrementally update dws_customer_360 for affected customers only.
    
    Instead of full rebuild, only updates customers that have new data
    in the current sync batch.
    """
    affected_customers = _get_affected_customers(batch_id)
    
    if not affected_customers:
        logger.info("  No affected customers, skipping customer_360 update")
        return 0
    
    logger.info("  Updating customer_360 for %d affected customers...", len(affected_customers))
    
    engine = get_etl_engine()
    updated_count = 0
    
    # Process in batches to avoid large IN clause
    batch_size = 100
    for i in range(0, len(affected_customers), batch_size):
        batch = affected_customers[i:i + batch_size]
        
        # Delete existing records for affected customers
        with engine.begin() as conn:
            conn.execute(
                text(
                    "DELETE FROM dws_customer_360 "
                    "WHERE customer_name IN :customers"
                ),
                {"customers": tuple(batch)}
            )
        
        # Rebuild aggregates for affected customers
        with engine.begin() as conn:
            result = conn.execute(
                text(
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
                    "WHERE icp.customer_name IN :customers "
                    "GROUP BY icp.customer_name "
                    "ON DUPLICATE KEY UPDATE "
                    "  interaction_count_total   = VALUES(interaction_count_total), "
                    "  interaction_count_30d     = VALUES(interaction_count_30d), "
                    "  last_interaction_time     = VALUES(last_interaction_time), "
                    "  last_interaction_channel  = VALUES(last_interaction_channel), "
                    "  top_channels              = VALUES(top_channels), "
                    "  updated_at                = NOW()"
                ),
                {"customers": tuple(batch)}
            )
            updated_count += result.rowcount
    
    logger.info("  customer_360 updated: %d customers", updated_count)
    return updated_count


def _incremental_build_contact_360(batch_id: int) -> int:
    """Incrementally update dws_contact_360 for affected customers only."""
    affected_customers = _get_affected_customers(batch_id)
    
    if not affected_customers:
        logger.info("  No affected customers, skipping contact_360 update")
        return 0
    
    logger.info("  Updating contact_360 for %d affected customers...", len(affected_customers))
    
    engine = get_etl_engine()
    updated_count = 0
    
    # Process in batches
    batch_size = 100
    for i in range(0, len(affected_customers), batch_size):
        batch = affected_customers[i:i + batch_size]
        
        # Delete existing records for affected customers
        with engine.begin() as conn:
            conn.execute(
                text(
                    "DELETE FROM dws_contact_360 "
                    "WHERE customer_id IN ("
                    "  SELECT id FROM dws_customer_360 "
                    "  WHERE customer_name IN :customers"
                    ")"
                ),
                {"customers": tuple(batch)}
            )
        
        # Rebuild contact 360 for affected customers
        with engine.begin() as conn:
            result = conn.execute(
                text(
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
                    "WHERE cm.customer_name IN :customers "
                    "ON DUPLICATE KEY UPDATE "
                    "  interaction_count     = VALUES(interaction_count), "
                    "  interaction_count_30d = VALUES(interaction_count_30d), "
                    "  last_interaction_time = VALUES(last_interaction_time), "
                    "  updated_at            = NOW()"
                ),
                {"customers": tuple(batch)}
            )
            updated_count += result.rowcount
    
    logger.info("  contact_360 updated: %d contacts", updated_count)
    return updated_count


def _incremental_rebuild_aggregates(batch_id: int) -> Dict[str, int]:
    """Incrementally rebuild customer_360 and contact_360 for affected customers only.
    
    Instead of full rebuild, only updates customers that have new data
    in the current sync batch.
    """
    logger.info("Incremental sync: Incrementally updating aggregate tables...")
    
    c360_count = _incremental_build_customer_360(batch_id)
    ct360_count = _incremental_build_contact_360(batch_id)
    
    return {"customer_360": c360_count, "contact_360": ct360_count}
