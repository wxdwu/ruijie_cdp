"""ETL 全量同步模块（full_sync/build_dws_contact_mapping.py）。从原 etl_sync.py 抽取，SQL 与调用语义保持不变。"""

from __future__ import annotations

import logging

from app.services.etl.common import *  # noqa: F401,F403

logger = logging.getLogger(__name__)



# 以下函数/常量由原 etl_sync.py 抽取，SQL 与调用语义保持不变
def _load_contact_mapping() -> Dict[str, int]:
    """Populate dws_contact_mapping from all ODS contact sources.

    Uses DELETE + INSERT per source to avoid duplicates (no unique constraint
    beyond auto-increment PK).  Relies on tmp_icp_customers / tmp_icp_mobiles
    and tmp_valid_linkflow_contacts being pre-populated.
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
        "  AND ( "
        "    c.customer_name IN (SELECT customer_name FROM tmp_icp_customers) "
        "    OR c.mobile IN (SELECT mobile FROM tmp_icp_mobiles) "
        "  )"
    )
    stats["crm"] = n
    logger.info("[b] CRM contacts (matched to zhique): %d rows", n)

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
    # Match linkflow contacts to CRM customers via mobile_phone.
    # The valid contacts have already been pre-computed in tmp_valid_linkflow_contacts.
    n = _exec(
        "INSERT IGNORE INTO dws_contact_mapping "
        "  (customer_name, contact_name, mobile, email, "
        "   linkflow_contact_id, source_table, etl_time) "
        "SELECT "
        "  lc.customer_name, lc.name, lc.mobile_phone, l.email, "
        "  lc.contact_id, 'linkflow', NOW() "
        "FROM tmp_valid_linkflow_contacts lc "
        "INNER JOIN ods_linkflow_contacts_day l ON l.contact_id = lc.contact_id"
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
