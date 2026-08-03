"""ETL 全量同步模块（full_sync/build_dws_customer_360.py）。从原 etl_sync.py 抽取，SQL 与调用语义保持不变。"""

from __future__ import annotations

import logging

from sqlalchemy import text

from app.services.etl.common import *  # noqa: F401,F403
from app.services.etl.common.legal_filter import (
    clean_dws_table_by_company_filter,
)

logger = logging.getLogger(__name__)



# 以下函数/常量由原 etl_sync.py 抽取，SQL 与调用语义保持不变
# base TLB dws_interaction_detail


def _customer_360_aggregate_insert(id_expr: str, where_clause: str) -> int:
    """按聚合结果写入 dws_customer_360 的公共 SQL。

    id_expr:      插入时的 id 表达式（已存在客户传 old.id，新客户传 NULL）
    where_clause: 控制只写入“已存在”或“新”客户（基于能否在交换后的服务表
                  dws_customer_360_temp 中匹配到 customer_name）
    """
    return _exec(
        "INSERT INTO dws_customer_360 ( "
        "  id, customer_name, interaction_count_total, interaction_count_30d, "
        "  last_interaction_time, last_interaction_channel, "
        "  top_channels, updated_at "
        ") "
        "SELECT "
        # 用 MAX 包裹 id 表达式以满足 only_full_group_by：dws_customer_360_temp.customer_name
        # 是唯一键，每个分组 old.id 至多一个值，MAX 结果等价于原值；NULL 分支 MAX(NULL) 仍为空，自增照常。
        f"  MAX({id_expr}) AS id, "
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
        "LEFT JOIN dws_interaction_detail i "
        "  ON i.customer_name COLLATE utf8mb4_0900_ai_ci "
        "   = icp.customer_name COLLATE utf8mb4_0900_ai_ci "
        "LEFT JOIN dws_customer_360_temp old "
        "  ON old.customer_name COLLATE utf8mb4_0900_ai_ci "
        "   = icp.customer_name COLLATE utf8mb4_0900_ai_ci "
        f"{where_clause} "
        "GROUP BY icp.customer_name "
        "ON DUPLICATE KEY UPDATE "
        "  interaction_count_total   = VALUES(interaction_count_total), "
        "  interaction_count_30d     = VALUES(interaction_count_30d), "
        "  last_interaction_time     = VALUES(last_interaction_time), "
        "  last_interaction_channel  = VALUES(last_interaction_channel), "
        "  top_channels              = VALUES(top_channels), "
        "  updated_at                = NOW()"
    )


def _build_customer_360() -> int:
    """Build dws_customer_360 from interaction_detail, CRM opps, and contacts.

    稳定 id 策略：全量重建不再 TRUNCATE 后任意重排 id。改为以交换后的服务表
    dws_customer_360_temp（持有当前对外服务的 id）为基准——已存在客户的 id 原样
    回填，仅新客户获得新 id，从而避免 id 漂移破坏 review_candidate /
    company_merge_map 的 id 引用。

    Requires tmp_crm_contact_attr and tmp_crm_opportunity_agg to be populated.
    """
    engine = get_etl_engine()

    # Phase 1: 稳定 id 重建。先清空当前构建目标表（交换后的旧 _backup 槽，其 id
    # 已过期、无需保留），再分阶段写入：已存在客户回填旧 id，新客户走自增。
    logger.info("稳定 id 重建 dws_customer_360（保留已存在客户 id，仅新客户获新 id）…")
    _exec("TRUNCATE TABLE dws_customer_360")

    logger.info("Phase 1a: 已存在客户按 dws_customer_360_temp 回填稳定 id…")
    n_existing = _customer_360_aggregate_insert(
        id_expr="old.id",
        where_clause="WHERE old.customer_name IS NOT NULL",
    )
    logger.info("  Phase 1a done: %d existing customers kept stable id", n_existing)

    # 将自增计数器抬到 max(id)+1，确保新客户（id=NULL）不会与已回填 id 撞车。
    with engine.begin() as conn:
        max_id = conn.execute(
            text("SELECT COALESCE(MAX(id), 0) FROM dws_customer_360")
        ).scalar()
        conn.execute(
            text(f"ALTER TABLE dws_customer_360 AUTO_INCREMENT = {int(max_id) + 1}")
        )
    logger.info("  AUTO_INCREMENT 已抬至 %d", int(max_id) + 1)

    logger.info("Phase 1b: 新客户获新 id…")
    n_new = _customer_360_aggregate_insert(
        id_expr="NULL",
        where_clause="WHERE old.customer_name IS NULL",
    )
    logger.info("  Phase 1b done: %d new customers inserted", n_new)

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

    # role_coverage & source_tables：先聚合到带主键索引的临时表，再做索引化 JOIN。
    # 原写法 UPDATE ... JOIN (SELECT ... GROUP BY customer_name) 的派生表无索引，
    # 会对 20万×20万 行做笛卡尔扫描（dws_contact_mapping 约 47万行），耗时数分钟、
    # 易超过 read_timeout(300s) 触发 2013。聚合一次即可同时算出两列。
    _exec("DROP TEMPORARY TABLE IF EXISTS tmp_contact_agg")
    _exec(
        "CREATE TEMPORARY TABLE tmp_contact_agg ( "
        "  customer_name VARCHAR(255) NOT NULL, "
        "  role_coverage VARCHAR(16) NOT NULL, "
        "  source_tables JSON, "
        "  PRIMARY KEY (customer_name) "
        ") "
        "SELECT "
        "  customer_name, "
        "  CASE "
        "    WHEN COUNT(DISTINCT CASE WHEN role_category = '决策者' THEN 1 END) > 0 "
        "     AND COUNT(DISTINCT CASE WHEN role_category = '技术评估者' THEN 1 END) > 0 "
        "     AND COUNT(DISTINCT CASE WHEN role_category = '使用者' THEN 1 END) > 0 "
        "    THEN '全' "
        "    WHEN COUNT(DISTINCT role_category) > 0 THEN '部分' "
        "    ELSE '无' "
        "  END AS role_coverage, "
        "  CAST(CONCAT('[', GROUP_CONCAT(DISTINCT CONCAT('\"', source_table, '\"')), ']') "
        "    AS JSON) AS source_tables "
        "FROM dws_contact_mapping "
        "GROUP BY customer_name"
    )
    _exec(
        "UPDATE dws_customer_360 c360 "
        "INNER JOIN tmp_contact_agg rm "
        "  ON rm.customer_name COLLATE utf8mb4_0900_ai_ci "
        "   = c360.customer_name COLLATE utf8mb4_0900_ai_ci "
        "SET c360.role_coverage = rm.role_coverage, "
        "    c360.source_tables = rm.source_tables"
    )
    _exec("DROP TEMPORARY TABLE IF EXISTS tmp_contact_agg")

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
        "      GREATEST("
        "        COALESCE(c360.intent_score, 0), "
        "        c360.interaction_count_30d * 2 "
        "        + IF(c360.active_opp_count > 0, 20, 0) "
        "        + IF(c360.contact_count >= 3, 10, c360.contact_count * 3) "
        "      )"
        "    ), "
        "  c360.intent_level = "
        "    ELT("
        "      GREATEST("
        "        COALESCE(FIELD(c360.intent_level, '无', '低', '中', '高'), 0), "
        "        CASE "
        "          WHEN c360.interaction_count_30d >= 10 AND c360.active_opp_count > 0 THEN 4 "
        "          WHEN c360.interaction_count_30d >= 3 THEN 3 "
        "          WHEN c360.interaction_count_total > 0 THEN 2 "
        "          ELSE 1 "
        "        END"
        "      ), '无', '低', '中', '高'"
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
