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
        "  i.customer_name, "
        "  COUNT(*) AS interaction_count_total, "
        "  SUM(CASE WHEN i.event_time >= DATE_SUB(NOW(), INTERVAL 30 DAY) "
        "      THEN 1 ELSE 0 END) AS interaction_count_30d, "
        "  MAX(i.event_time) AS last_interaction_time, "
        "  SUBSTRING_INDEX( "
        "    GROUP_CONCAT(DISTINCT i.channel ORDER BY i.channel SEPARATOR ','), "
        "    ',', 1 "
        "  ) AS last_interaction_channel, "
        "  CAST( "
        "    CONCAT('[', GROUP_CONCAT(DISTINCT CONCAT('\"', i.channel, '\"')), ']') "
        "    AS JSON "
        "  ) AS top_channels, "
        "  NOW() "
        "FROM dws_interaction_detail i "
        "WHERE i.customer_name IS NOT NULL AND i.customer_name != '' "
        "GROUP BY i.customer_name "
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
        "  cm.id AS customer_id, "
        "  cm.contact_name, cm.mobile, cm.email, cm.department, cm.position, "
        "  cm.purchase_role, cm.role_category, "
        "  COALESCE(agg.interaction_count, 0), "
        "  COALESCE(agg.interaction_count_30d, 0), "
        "  agg.last_interaction_time, "
        "  CAST(CONCAT('[\"', cm.source_table, '\"]') AS JSON), "
        "  cm.linkflow_contact_id, "
        "  NOW() "
        "FROM dws_contact_mapping cm "
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
