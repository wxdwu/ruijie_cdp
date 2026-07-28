"""ETL 全量同步模块（full_sync/build_dws_customer_360.py）。从原 etl_sync.py 抽取，SQL 与调用语义保持不变。"""

from __future__ import annotations

import logging

from app.services.etl.common import *  # noqa: F401,F403
from app.services.etl.common.legal_filter import (
    clean_dws_table_by_company_filter,
)

logger = logging.getLogger(__name__)



# 以下函数/常量由原 etl_sync.py 抽取，SQL 与调用语义保持不变
# base TLB dws_interaction_detail
def _build_customer_360() -> int:
    """Build dws_customer_360 from interaction_detail, CRM opps, and contacts.

    Three-phase approach:
    1. INSERT interaction aggregates from dws_interaction_detail
    2. UPDATE with pre-aggregated CRM contact attributes from tmp_crm_contact_attr
    3. UPDATE with pre-aggregated CRM opportunity metrics from tmp_crm_opportunity_agg
    4. UPDATE derived fields (role_coverage, data_coverage, source_tables)

    Requires tmp_crm_contact_attr and tmp_crm_opportunity_agg to be populated.
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

    # ── Phase 2: Enrich with pre-aggregated CRM contact attributes ───────
    logger.info("Phase 2: Enriching with CRM contact attributes…")
    n = _exec(
        "UPDATE dws_customer_360 c360 "
        "INNER JOIN tmp_crm_contact_attr crm "
        "  ON crm.customer_name COLLATE utf8mb4_0900_ai_ci "
        "   = c360.customer_name COLLATE utf8mb4_0900_ai_ci "
        "SET "
        "  c360.industry       = COALESCE(crm.industry, c360.industry), "
        "  c360.region         = COALESCE(crm.region, c360.region), "
        "  c360.owner_name     = COALESCE(crm.owner_name, c360.owner_name), "
        "  c360.attribute      = COALESCE(crm.attribute, c360.attribute), "
        "  c360.contact_count  = crm.contact_count, "
        "  c360.mobile_count   = crm.mobile_count"
    )
    logger.info("Phase 2 done: %d rows enriched", n)

    # ── Phase 3: Enrich with pre-aggregated CRM opportunity metrics ──────
    logger.info("Phase 3: Enriching with CRM opportunity metrics…")
    n = _exec(
        "UPDATE dws_customer_360 c360 "
        "INNER JOIN tmp_crm_opportunity_agg opp "
        "  ON opp.customer_name COLLATE utf8mb4_0900_ai_ci "
        "   = c360.customer_name COLLATE utf8mb4_0900_ai_ci "
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

    # ── Phase 5: Enrich/Insert with ods_key_customer (重要客户) ─────────
    # 重要客户目前不需要再添加到之前的数据里面
    # 单独开一栏展示
    logger.info("Phase 5: Enriching with ods_key_customer...")

    # Step 1: UPDATE existing customers (match by key_customer_name -> customer_name)
    # 字段映射：
    #   ods.key_customer_name -> dws.customer_name (客户公司名称, 用于匹配)
    #   ods.customer_name      -> dws.owner_name    (客户公司负责人)
    #   ods.department_level3  -> dws.region        (区域)
    #   ods.industry_category  -> dws.industry      (行业)
    #   ods.attribute          -> dws.attribute     (属性 H/M/L/空)
    n = _exec(
        "UPDATE dws_customer_360 c360 "
        "INNER JOIN ods_key_customer kc "
        "  ON kc.key_customer_name = c360.customer_name COLLATE utf8mb4_0900_ai_ci "
        "SET "
        "  c360.owner_name = COALESCE(kc.customer_name, c360.owner_name), "
        "  c360.region    = COALESCE(kc.department_level3, c360.region), "
        "  c360.industry  = COALESCE(kc.industry_category, c360.industry), "
        "  c360.attribute = COALESCE(kc.attribute, c360.attribute)"
    )
    logger.info("  Updated %d rows by key_customer_name", n)

    # Step 2: INSERT new customers (by key_customer_name)，先按公司名规则过滤再聚合
    key_rows = read_filtered_key_customers()
    n = bulk_insert_key_customers(key_rows, "dws_customer_360")
    logger.info("  Inserted %d new rows by key_customer_name (filtered)", n)
    logger.info("Phase 5 done: ods_key_customer enriched")

    # 聚合完成后,按 company_filter 规则清理不合法公司名(确保 dws 数据合法,
    # 且与前端客户列表筛选口径一致)。dws_customer_360 含 contact_count /
    # interaction_count_total 列,启用保命条件(有联系人或互动则保留)。
    clean_dws_table_by_company_filter(
        "dws_customer_360", "customer_name", use_lifeline=True
    )

    total = _table_count("dws_customer_360")
    logger.info("Customer 360 complete: %d rows", total)
    return total
