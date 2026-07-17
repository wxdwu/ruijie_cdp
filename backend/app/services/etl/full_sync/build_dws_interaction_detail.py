"""ETL 全量同步模块（full_sync/build_dws_interaction_detail.py）。从原 etl_sync.py 抽取，SQL 与调用语义保持不变。"""

from __future__ import annotations

import logging

from app.services.etl.common import *  # noqa: F401,F403

logger = logging.getLogger(__name__)



# 以下函数/常量由原 etl_sync.py 抽取，SQL 与调用语义保持不变
def _load_interactions_zhique() -> int:
    """Load Zhique behaviors → dws_interaction_detail.

    Uses tmp_crm_mobiles to drive the mobile_phone index on
    ods_zhique_behavior_list_day, avoiding a full id-range scan.
    """
    channel_case = _build_zhique_channel_case()
    total_mobiles = _table_count("tmp_crm_mobiles")
    logger.info(
        "  Loading Zhique behaviors using %d CRM mobiles...",
        total_mobiles,
    )

    n = _exec(
        "INSERT IGNORE INTO dws_interaction_detail "
        "  (customer_name, contact_name, mobile, source_table, "
        "   channel, behavior_type, content, event_time, source_id, etl_time) "
        "SELECT "
        "  cm.customer_name, b.contact_name, b.mobile_phone, 'zhique', "
        f"  {channel_case}, b.behavior_type, b.behavior_name, "
        "  b.behavior_time, b.behavior_id, NOW() "
        "FROM ods_zhique_behavior_list_day b "
        "INNER JOIN tmp_crm_mobiles m ON m.mobile = b.mobile_phone "
        "INNER JOIN ods_crm_contact_day cm ON cm.mobile = b.mobile_phone "
        "  AND cm.customer_name IS NOT NULL AND cm.customer_name != '' "
    )

    logger.info("  Zhique behaviors → interaction_detail: %d rows", n)
    return n


def _load_interactions_tianrun() -> int:
    """Load Tianrun sessions → dws_interaction_detail.

    Tianrun sessions are online customer-service chats.  The visitor_mobile_phone
    is NULL for all rows.  We use visitor_name as the contact identifier and the
    contact_type_name as the channel source.

    重要：天润会话的 customer_name 是「地域/访客标签」(例如 “江苏徐州3e9a6c”、
    “网页1a6353”)，并非真实公司名。若直接写入 dws_interaction_detail，会污染
    customer_name 维度（下游 dws_customer_360 / dws_contact_360 都以
    customer_name 为聚合键）。因此这里与增量模式保持一致，只保留
    customer_name 命中 ICP 客户白名单 (tmp_icp_customers) 的会话，避免把
    地名/访客标签当公司名入库。

    customer_name 在 ods_tianrun_session_day 上没有索引，故仍做一次整表扫描，
    仅靠 tmp_icp_customers 的小表 JOIN 过滤。
    """
    total_rows = _table_count("ods_tianrun_session_day")
    logger.info(
        "  Loading Tianrun sessions (single pass over %d rows, "
        "filtered by tmp_icp_customers)...",
        total_rows,
    )

    n = _exec(
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
        "INNER JOIN tmp_icp_customers icp ON icp.customer_name = s.customer_name "
        "WHERE s.customer_name IS NOT NULL AND s.customer_name != '' "
        "  AND s.visitor_name IS NOT NULL AND s.visitor_name != ''"
    )

    logger.info("  Tianrun sessions → interaction_detail: %d rows", n)
    return n


def _load_interactions_linkflow() -> int:
    """Load Linkflow events → dws_interaction_detail.

    Drives the query from tmp_valid_linkflow_contacts (small) and uses the
    idx_lfe_cid index on ods_linkflow_events_day.contact_id.  With only a few
    hundred valid contacts, a single INSERT ... SELECT is faster than batching
    by contact_id and avoids extra round-trips.
    """
    # 写入前先确保目标表含 interaction_content 字段，缺失则更新表结构
    _ensure_interaction_content_column()

    total_contacts = _table_count("tmp_valid_linkflow_contacts")
    logger.info(
        "  Loading Linkflow events using %d valid contacts...",
        total_contacts,
    )

    n = _exec(
        "INSERT IGNORE INTO dws_interaction_detail "
        "  (customer_name, contact_name, mobile, source_table, "
        "   channel, behavior_type, event_time, source_id, etl_time, "
        "   interaction_content) "
        "SELECT "
        "  lc.customer_name, lc.name, lc.mobile_phone, 'linkflow', "
        "  'web', e.event_name, "
        "  FROM_UNIXTIME(e.event_date_ms / 1000), "
        "  e.event_id, NOW(), "
        "  LEFT(NULLIF(TRIM(JSON_UNQUOTE(JSON_EXTRACT( "
        "    CASE WHEN JSON_VALID(e.props_json) THEN e.props_json ELSE '{}' END, "
        "    '$.s_title'))), ''), 100) "
        "FROM ods_linkflow_events_day e "
        "INNER JOIN tmp_valid_linkflow_contacts lc ON lc.contact_id = e.contact_id"
    )

    logger.info("  Linkflow events → interaction_detail: %d rows", n)
    return n


def _load_interactions_crm_lead() -> int:
    """Load CRM leads (ods_crm_lead_data_day) → dws_interaction_detail.

    线索表为全量更新，整表扫描即可。一条线索视为一次客户交互（线索获取）：
    - customer_name ← 客户单位，contact_name ← 客户姓名，mobile ← 联系电话
    - source_id 用行内容稳定哈希（bigint），靠 (source_table, source_id) 唯一键去重
    """
    logger.info("  Loading CRM leads → interaction_detail ...")
    n = _exec(
        "INSERT IGNORE INTO dws_interaction_detail "
        "  (customer_name, contact_name, mobile, source_table, "
        "   channel, behavior_type, content, event_time, source_id, etl_time) "
        "SELECT "
        "  NULLIF(TRIM(l.`客户单位`), ''), "
        "  NULLIF(TRIM(l.`客户姓名`), ''), "
        "  NULLIF(TRIM(l.`联系电话`), ''), "
        "  'crm_lead', "
        "  COALESCE(NULLIF(TRIM(l.`线索来源大类`), ''), 'crm'), "
        "  '线索', "
        "  COALESCE(NULLIF(TRIM(l.`活动名称`), ''), NULLIF(TRIM(l.`线索来源类型`), ''), ''), "
        "  l.`线索获得日期`, "
        "  CAST(CONV(SUBSTRING(MD5(CONCAT_WS('|', l.`线索编号`, l.`客户单位`, "
        "        l.`客户姓名`, l.`联系电话`, l.`线索获得日期`, l.`活动名称`)), 1, 15), 16, 10) "
        "       AS UNSIGNED), "
        "  NOW() "
        "FROM ods_crm_lead_data_day l "
        "WHERE NULLIF(TRIM(l.`客户单位`), '') IS NOT NULL "
        "  AND l.`线索获得日期` IS NOT NULL"
    )
    logger.info("  CRM leads → interaction_detail: %d rows", n)
    return n


def _load_interactions_crm_opportunity() -> int:
    """Load CRM opportunities (ods_crm_opportunity_data_day) → dws_interaction_detail.

    商机表为全量更新，整表扫描即可。一条商机视为一次客户交互（商机创建）：
    - customer_name ← 客户名；contact_name ← 业务机会所有人名称（商机联系人/负责人），
      mobile 在商机表中无对应字段，置空
    - source_id 用行内容稳定哈希（bigint），靠 (source_table, source_id) 唯一键去重
    """
    logger.info("  Loading CRM opportunities → interaction_detail ...")
    n = _exec(
        "INSERT IGNORE INTO dws_interaction_detail "
        "  (customer_name, contact_name, mobile, source_table, "
        "   channel, behavior_type, content, event_time, source_id, etl_time) "
        "SELECT "
        "  NULLIF(TRIM(o.`客户名`), ''), "
        "  NULLIF(TRIM(o.`业务机会所有人名称`), ''), "
        "  NULL, "
        "  'crm_opportunity', "
        "  COALESCE(NULLIF(TRIM(o.`商机来源`), ''), 'crm'), "
        "  '商机', "
        "  COALESCE(NULLIF(TRIM(o.`业务机会名称`), ''), ''), "
        "  o.`创建日期-转化`, "
        "  CAST(CONV(SUBSTRING(MD5(CONCAT_WS('|', o.`业务机会编码`, o.`客户名`, "
        "        o.`业务机会名称`, o.`创建日期-转化`, o.`商机来源`)), 1, 15), 16, 10) "
        "       AS UNSIGNED), "
        "  NOW() "
        "FROM ods_crm_opportunity_data_day o "
        "WHERE NULLIF(TRIM(o.`客户名`), '') IS NOT NULL "
        "  AND o.`创建日期-转化` IS NOT NULL"
    )
    logger.info("  CRM opportunities → interaction_detail: %d rows", n)
    return n


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
    stats["crm_lead"] = _load_interactions_crm_lead()
    stats["crm_opportunity"] = _load_interactions_crm_opportunity()

    total = sum(stats.values())
    logger.info(
        "Interaction detail complete: %d total rows  %s",
        total, stats,
    )
    return stats
