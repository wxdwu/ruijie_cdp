"""ETL 增量同步模块（incremental_sync/build_dws_contact_360.py）。从原 etl_sync.py 抽取，SQL 与调用语义保持不变。"""

from __future__ import annotations

import logging

from app.services.etl.common import *  # noqa: F401,F403

logger = logging.getLogger(__name__)



# 以下函数/常量由原 etl_sync.py 抽取，SQL 与调用语义保持不变
def _build_contact_360(
    target: str = "dws_contact_360",
    mapping_tbl: str = "dws_contact_mapping",
    interaction_tbl: str = "dws_interaction_detail",
    customer_tbl: str = "dws_customer_360",
) -> int:
    """从 contact_mapping + interaction_detail 构建 dws_contact_360。

    通过参数化表名，增量同步可传入 *_temp 基表来重建临时表，从而与全量同步
    得到完全一致的结果（避免此前“仅重建受影响客户”时 DELETE/INSERT 键不一致
    导致 dws_contact_360 行数偏差）。
    """
    logger.info("Truncating %s for full rebuild…", target)
    _exec(f"TRUNCATE TABLE {target}")

    logger.info("Building contact-level interaction aggregates…")
    _exec("TRUNCATE TABLE tmp_contact_interactions")
    agg_rows = _exec(
        "INSERT INTO tmp_contact_interactions "
        "  (contact_name, mobile, interaction_count, interaction_count_30d, "
        "   last_interaction_time) "
        "SELECT "
        "  contact_name, mobile, "
        "  COUNT(*) AS interaction_count, "
        "  SUM(CASE WHEN event_time >= DATE_SUB(NOW(), INTERVAL 30 DAY) "
        "      THEN 1 ELSE 0 END) AS interaction_count_30d, "
        "  MAX(event_time) AS last_interaction_time "
        f"FROM {interaction_tbl} "
        "WHERE contact_name IS NOT NULL "
        "GROUP BY contact_name, mobile"
    )
    logger.info("Contact interaction aggregates ready: %d rows", agg_rows)

    logger.info("Building contact-level 360 aggregates…")

    n = _exec(
        "INSERT IGNORE INTO " + target + " ( "
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
        f"FROM {mapping_tbl} cm "
        # 只保留公司名存在于 ICP 白名单(tmp_icp_customers)的联系人：
        # 能进入 dws_contact_360 的联系人，其公司必须是 tmp_icp_customers 中
        # 存在的公司，从而有合法的非零 customer_id；过滤掉无对应客户
        # （customer_id = 0 / NULL）的孤儿联系人。
        f"INNER JOIN tmp_icp_customers icp ON icp.customer_name = cm.customer_name "
        f"LEFT JOIN {customer_tbl} c360 ON c360.customer_name = cm.customer_name "
        "LEFT JOIN tmp_contact_interactions agg "
        "  ON agg.contact_name = cm.contact_name "
        " AND agg.mobile <=> cm.mobile "
        "WHERE c360.id IS NOT NULL AND c360.id != 0 "
        "ON DUPLICATE KEY UPDATE "
        "  interaction_count     = VALUES(interaction_count), "
        "  interaction_count_30d = VALUES(interaction_count_30d), "
        "  last_interaction_time = VALUES(last_interaction_time), "
        "  updated_at            = NOW()"
    )

    # Compute activity_level
    _exec(
        f"UPDATE {target} SET "
        "  activity_level = CASE "
        "    WHEN interaction_count_30d >= 10 THEN 'high' "
        "    WHEN interaction_count_30d >= 3 THEN 'medium' "
        "    WHEN interaction_count > 0 THEN 'low' "
        "    ELSE 'none' "
        "  END"
    )

    total = _table_count(target)
    logger.info("Contact 360 complete: %d rows (affected %d)", total, n)
    return total


def _incremental_build_contact_360(batch_id: int) -> int:
    """增量同步时完整重建 dws_contact_360_temp（与全量同步逻辑完全一致）。

    不再“仅重建受影响客户”，改用与全量同步完全相同的构建逻辑（仅基表换成
    *_temp），从根上消除 DELETE/INSERT 键不一致导致的行数偏差，保证增量结果
    与全量结果一致。
    """
    logger.info("Incremental sync: full rebuild of contact_360 (temp) ...")
    return _build_contact_360(
        target="dws_contact_360_temp",
        mapping_tbl="dws_contact_mapping_temp",
        interaction_tbl="dws_interaction_detail_temp",
        customer_tbl="dws_customer_360_temp",
    )
