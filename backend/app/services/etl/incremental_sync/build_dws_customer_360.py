"""ETL 增量同步模块（incremental_sync/build_dws_customer_360.py）。从原 etl_sync.py 抽取，SQL 与调用语义保持不变。"""

from __future__ import annotations

import logging
from sqlalchemy import text

from app.services.etl.common import *  # noqa: F401,F403
from app.services.etl.incremental_sync.build_dws_contact_360 import (
    _build_contact_360, _incremental_build_contact_360)
from app.services.etl.common.interaction_align import align_interaction_detail_names

logger = logging.getLogger(__name__)



# 以下函数/常量由原 etl_sync.py 抽取，SQL 与调用语义保持不变
def _get_affected_customers(batch_id: int) -> List[str]:
    """Get list of customer names affected by current sync batch.
    
    Customers are affected if they have:
    1. New interactions in this batch (sync_batch_id match)
    2. New contact mappings in this batch (sync_batch_id match)
    3. Exist in tmp_icp_customers but not in dws_customer_360_temp (new ICP customers)
    
    Note: During incremental sync, we query the *_temp tables where new data is stored.
    """
    engine = get_etl_engine()
    customers = []
    
    # Determine if temp tables exist (meaning we're in incremental sync)
    # Check for any temp table to determine if we should use temp tables
    use_temp_tables = False
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'app_cdp' "
                "  AND table_name = 'dws_contact_mapping_temp' "
                "LIMIT 1"
            )
        )
        if result.fetchone():
            use_temp_tables = True
    
    # Get customers with new interactions
    interaction_table = "dws_interaction_detail_temp" if use_temp_tables else "dws_interaction_detail"
    with engine.connect() as conn:
        result = conn.execute(
            text(
                f"SELECT DISTINCT customer_name FROM {interaction_table} "
                "WHERE sync_batch_id = :batch_id AND customer_name IS NOT NULL"
            ),
            {"batch_id": batch_id}
        )
        customers.extend(row[0] for row in result.fetchall())
    
    # Get customers with new contact mappings
    mapping_table = "dws_contact_mapping_temp" if use_temp_tables else "dws_contact_mapping"
    with engine.connect() as conn:
        result = conn.execute(
            text(
                f"SELECT DISTINCT customer_name FROM {mapping_table} "
                f"WHERE sync_batch_id = :batch_id AND customer_name IS NOT NULL"
            ),
            {"batch_id": batch_id}
        )
        customers.extend(row[0] for row in result.fetchall())
    
    # Get ICP customers that are in tmp_icp_customers but not in dws_customer_360_temp
    # (newly added customers that need to be built)
    customer_360_table = "dws_customer_360_temp" if use_temp_tables else "dws_customer_360"
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT DISTINCT icp.customer_name "
                "FROM tmp_icp_customers icp "
                f"LEFT JOIN {customer_360_table} c360 ON icp.customer_name = c360.customer_name "
                "WHERE c360.customer_name IS NULL"
            )
        )
        customers.extend(row[0] for row in result.fetchall())
    
    # Remove duplicates
    return list(set(customers))


def _incremental_build_customer_360(batch_id: int) -> int:
    """Incrementally update dws_customer_360 for affected customers only.
    
    Instead of full rebuild, only updates customers that have new data
    in the current sync batch.
    
    Complete update including:
    - Phase 1: Interaction aggregates
    - Phase 2: CRM contact attributes (industry, region, owner_name, etc.)
    - Phase 3: CRM opportunity metrics (purchase_stage, opp amounts, etc.)
    - Phase 4: Derived fields (role_coverage, source_tables, data_coverage, intent)
    """
    affected_customers = _get_affected_customers(batch_id)
    
    if not affected_customers:
        logger.info("  No affected customers, skipping customer_360 update")
        return 0
    
    logger.info("  Updating customer_360 for %d affected customers...", len(affected_customers))
    
    engine = get_etl_engine()
    
    # Process in batches to avoid large IN clause
    batch_size = 100
    total_updated = 0
    
    for i in range(0, len(affected_customers), batch_size):
        batch = affected_customers[i:i + batch_size]
        logger.info("    Processing batch %d-%d...", i, min(i + batch_size, len(affected_customers)))
        
        # ── Phase 1: Insert/Update interaction aggregates ─────────────
        with engine.begin() as conn:
            result = conn.execute(
                text(
                    "INSERT INTO dws_customer_360_temp ( "
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
                    "LEFT JOIN dws_interaction_detail_temp i ON i.customer_name COLLATE utf8mb4_0900_ai_ci = icp.customer_name COLLATE utf8mb4_0900_ai_ci "
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
            total_updated += result.rowcount
        
        # ── Phase 2: Enrich with pre-aggregated CRM contact attributes ─────────────
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE dws_customer_360_temp c360 "
                    "INNER JOIN tmp_crm_contact_attr crm "
                    "  ON crm.customer_name COLLATE utf8mb4_0900_ai_ci "
                    "   = c360.customer_name COLLATE utf8mb4_0900_ai_ci "
                    "SET "
                    "  c360.industry       = COALESCE(crm.industry, c360.industry), "
                    "  c360.region         = COALESCE(crm.region, c360.region), "
                    "  c360.owner_name     = COALESCE(crm.owner_name, c360.owner_name), "
                    "  c360.attribute      = COALESCE(crm.attribute, c360.attribute), "
                    "  c360.contact_count  = crm.contact_count, "
                    "  c360.mobile_count   = crm.mobile_count "
                    "WHERE c360.customer_name IN :customers"
                ),
                {"customers": tuple(batch)}
            )

        # ── Phase 3: Enrich with pre-aggregated CRM opportunity metrics ─────────────
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE dws_customer_360_temp c360 "
                    "INNER JOIN tmp_crm_opportunity_agg opp "
                    "  ON opp.customer_name COLLATE utf8mb4_0900_ai_ci "
                    "   = c360.customer_name COLLATE utf8mb4_0900_ai_ci "
                    "SET "
                    "  c360.purchase_stage    = opp.purchase_stage, "
                    "  c360.forecast_type     = opp.forecast_type, "
                    "  c360.active_opp_count  = opp.active_opp_count, "
                    "  c360.active_opp_amount = opp.active_opp_amount, "
                    "  c360.funnel_opp_count  = opp.funnel_opp_count, "
                    "  c360.won_amount        = opp.won_amount "
                    "WHERE c360.customer_name IN :customers"
                ),
                {"customers": tuple(batch)}
            )
    
    # ── Phase 4: Derived fields (process all affected customers together) ──
    logger.info("    Updating derived fields (role_coverage, source_tables, data_coverage, intent)...")
    
    # role_coverage
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE dws_customer_360_temp c360 "
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
                "  FROM dws_contact_mapping_temp "
                "  WHERE customer_name IN :customers "
                "  GROUP BY customer_name "
                ") rm ON rm.customer_name = c360.customer_name "
                "SET c360.role_coverage = rm.role_coverage"
            ),
            {"customers": tuple(affected_customers)}
        )
    
    # source_tables
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE dws_customer_360_temp c360 "
                "INNER JOIN ( "
                "  SELECT customer_name, "
                "    CAST(CONCAT('[', GROUP_CONCAT(DISTINCT "
                "      CONCAT('\"', source_table, '\"') "
                "    ), ']') AS JSON) AS source_tables "
                "  FROM dws_contact_mapping_temp "
                "  WHERE customer_name IN :customers "
                "  GROUP BY customer_name "
                ") st ON st.customer_name = c360.customer_name "
                "SET c360.source_tables = st.source_tables"
            ),
            {"customers": tuple(affected_customers)}
        )
    
    # data_coverage & intent scoring
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE dws_customer_360_temp c360 "
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
                "  END "
                "WHERE c360.customer_name IN :customers"
            ),
            {"customers": tuple(affected_customers)}
        )
    
    # ── Phase 5: Enrich/Insert with ods_key_customer (重要客户) ─────────
    logger.info("    Enriching with ods_key_customer...")

    # Step 1: UPDATE existing customers (match by key_customer_name -> customer_name)
    # 字段映射：
    #   ods.key_customer_name -> dws.customer_name (客户公司名称, 用于匹配)
    #   ods.customer_name      -> dws.owner_name    (客户公司负责人)
    #   ods.department_level3  -> dws.region        (区域)
    #   ods.industry_category  -> dws.industry      (行业)
    #   ods.attribute          -> dws.attribute     (属性 H/M/L/空)
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE dws_customer_360_temp c360 "
                "INNER JOIN ods_key_customer kc "
                "  ON kc.key_customer_name = c360.customer_name COLLATE utf8mb4_0900_ai_ci "
                "SET "
                "  c360.owner_name = COALESCE(kc.customer_name, c360.owner_name), "
                "  c360.region    = COALESCE(kc.department_level3, c360.region), "
                "  c360.industry  = COALESCE(kc.industry_category, c360.industry), "
                "  c360.attribute = COALESCE(kc.attribute, c360.attribute) "
                "WHERE c360.customer_name IN :customers"
            ),
            {"customers": tuple(affected_customers)}
        )

    # Step 2: INSERT new customers (by key_customer_name)，先按公司名规则过滤再聚合
    logger.info("    Inserting filtered key customers into dws_customer_360_temp...")
    key_rows = read_filtered_key_customers()
    bulk_insert_key_customers(key_rows, "dws_customer_360_temp")

    logger.info("  customer_360 updated: %d customers (complete with Phase 1-5)", total_updated)
    return total_updated


def _incremental_rebuild_aggregates(batch_id: int) -> Dict[str, int]:
    """Incrementally rebuild customer_360 and contact_360 for affected customers only.
    
    Instead of full rebuild, only updates customers that have new data
    in the current sync batch.
    """
    logger.info("Incremental sync: Incrementally updating aggregate tables...")
    
    c360_count = _incremental_build_customer_360(batch_id)
    # 对齐互动明细 customer_name 到 customer_360 标准拼写（基于 _temp 表，旋转后生效）
    align_interaction_detail_names("dws_customer_360_temp", "dws_interaction_detail_temp")
    ct360_count = _incremental_build_contact_360(batch_id)
    
    return {"customer_360": c360_count, "contact_360": ct360_count}
