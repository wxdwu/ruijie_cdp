"""ETL 增量同步模块（incremental_sync/build_dws_interaction_detail.py）。从原 etl_sync.py 抽取，SQL 与调用语义保持不变。"""

from __future__ import annotations

import logging
from sqlalchemy import text

from app.services.etl.common import *  # noqa: F401,F403

logger = logging.getLogger(__name__)



# 以下函数/常量由原 etl_sync.py 抽取，SQL 与调用语义保持不变
def _incremental_upsert_interaction_detail(batch_id: int) -> Dict[str, int]:
    """True incremental UPSERT into dws_interaction_detail.
    
    Uses single INSERT IGNORE ... SELECT for optimal performance.
    Only processes ICP customer data (small dataset, no batching needed).
    """
    stats: Dict[str, int] = {}
    
    logger.info("Incremental sync: UPSERT dws_interaction_detail (true incremental)...")
    
    # 各表的增量水位由配置驱动（见 _watermark_filter），此处不再单独取 last_sync_time
    
    # Zhique behaviors - single INSERT IGNORE ... SELECT
    channel_case = _build_zhique_channel_case()
    zhique_filter = ""
    zhique_params: Dict[str, Any] = {"batch_id": batch_id}

    zhique_filter, _wm = _watermark_filter("ods_zhique_behavior_list_day", "b")
    if _wm is not None:
        zhique_params["watermark"] = _wm
        logger.info("  Zhique: filtering behaviors by watermark")

    engine = get_etl_engine()
    sql = text(
        "INSERT IGNORE INTO dws_interaction_detail_temp "
        "  (customer_name, contact_name, mobile, source_table, "
        "   channel, behavior_type, content, event_time, source_id, etl_time, sync_batch_id) "
        "SELECT "
        "  cm.customer_name, b.contact_name, b.mobile_phone, 'zhique', "
        f"  {channel_case}, b.behavior_type, b.behavior_name, "
        "  b.behavior_time, b.id, NOW(), :batch_id "
        "FROM ods_zhique_behavior_list_day b "
        "INNER JOIN tmp_crm_mobiles m ON m.mobile = b.mobile_phone "
        "INNER JOIN ods_crm_contact_day cm ON cm.mobile = b.mobile_phone "
        "  AND cm.customer_name IS NOT NULL AND cm.customer_name != '' "
        f"  {zhique_filter}"
    )
    
    with engine.begin() as conn:
        result = conn.execute(sql, zhique_params)
        stats["zhique"] = result.rowcount
    
    logger.info("  Zhique: %d new interactions (incremental)", stats["zhique"])
    _set_watermark_after_load("ods_zhique_behavior_list_day")
    
    # Tianrun sessions - single INSERT IGNORE ... SELECT（水位在内部按配置计算）
    stats["tianrun"] = _incremental_load_tianrun(batch_id)
    _set_watermark_after_load("ods_tianrun_session_day")

    # Linkflow events - single INSERT IGNORE ... SELECT（水位在内部按配置计算）
    stats["linkflow"] = _incremental_load_linkflow(batch_id)
    _set_watermark_after_load("ods_linkflow_events_day")

    # CRM 线索 / 商机（全量模式：每轮整表重跑，靠 (source_table, source_id) 唯一键去重）
    stats["crm_lead"] = _incremental_load_crm_lead(batch_id)
    stats["crm_opportunity"] = _incremental_load_crm_opportunity(batch_id)

    # 精确统计各数据源的实际影响行数（避免使用不准确的 rowcount）
    accurate_stats = _get_accurate_stats_by_source("dws_interaction_detail", batch_id)
    # 用精确统计的结果更新 stats
    for source, count in accurate_stats.items():
        stats[source] = count
    
    logger.info("Incremental sync: interaction detail done, stats=%s", stats)
    return stats


def _incremental_load_tianrun(batch_id: int) -> int:
    """True incremental load of new Tianrun sessions.

    按配置（ods_tianrun_session_day: start_time_sec / unix_time）计算水位过滤，
    仅处理 start_time_sec 大于上一轮最大水位的会话。
    """
    engine = get_etl_engine()

    # 按配置计算水位过滤（start_time_sec 用 FROM_UNIXTIME 比较）
    time_filter, _wm = _watermark_filter("ods_tianrun_session_day", "s")
    params: Dict[str, Any] = {"batch_id": batch_id}

    if _wm is not None:
        params["watermark"] = _wm
        logger.info("  Tianrun: filtering sessions by watermark")

    sql = text(
        "INSERT IGNORE INTO dws_interaction_detail_temp "
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
        "INNER JOIN tmp_icp_customers icp ON icp.customer_name = s.customer_name "
        f" {time_filter} "
        "  AND s.customer_name IS NOT NULL AND s.customer_name != ''"
    )

    with engine.begin() as conn:
        result = conn.execute(sql, params)
        inserted = result.rowcount

    logger.info("  Tianrun: %d new interactions (incremental)", inserted)
    return inserted


def _incremental_load_linkflow(batch_id: int) -> int:
    """True incremental load of new Linkflow events.

    按配置（ods_linkflow_events_day: extra_id / id）计算水位过滤，
    仅处理 extra_id 大于上一轮最大 id 的事件。
    """
    # 写入前先确保目标表（含增量临时表）含 interaction_content 字段
    _ensure_interaction_content_column()

    engine = get_etl_engine()

    # 按配置计算水位过滤（extra_id 最大 ID 水位）
    time_filter, _wm = _watermark_filter("ods_linkflow_events_day", "e")
    params: Dict[str, Any] = {"batch_id": batch_id}

    if _wm is not None:
        params["watermark"] = _wm
        logger.info("  Linkflow: filtering events by watermark")

    sql = text(
        "INSERT IGNORE INTO dws_interaction_detail_temp "
        "  (customer_name, contact_name, mobile, source_table, "
        "   channel, behavior_type, event_time, source_id, etl_time, "
        "   sync_batch_id, interaction_content) "
        "SELECT "
        "  lc.customer_name, lc.name, lc.mobile_phone, 'linkflow', "
        "  'web', e.event_name, "
        "  FROM_UNIXTIME(e.event_date_ms / 1000), "
        "  e.event_id, NOW(), :batch_id, "
        "  LEFT(NULLIF(TRIM(JSON_UNQUOTE(JSON_EXTRACT( "
        "    CASE WHEN JSON_VALID(e.props_json) THEN e.props_json ELSE '{}' END, "
        "    '$.s_title'))), ''), 100) "
        "FROM ods_linkflow_events_day e "
        "INNER JOIN tmp_valid_linkflow_contacts lc ON lc.contact_id = e.contact_id "
        f" {time_filter} "
    )

    with engine.begin() as conn:
        result = conn.execute(sql, params)
        inserted = result.rowcount

    logger.info("  Linkflow: %d new interactions (incremental)", inserted)
    return inserted


def _incremental_load_crm_lead(batch_id: int) -> int:
    """增量同步：整表重跑 CRM 线索（全量模式），靠 (source_table, source_id) 唯一键去重。"""
    engine = get_etl_engine()
    sql = text(
        "INSERT IGNORE INTO dws_interaction_detail_temp "
        "  (customer_name, contact_name, mobile, source_table, "
        "   channel, behavior_type, content, event_time, source_id, etl_time, sync_batch_id) "
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
        "  NOW(), :batch_id "
        "FROM ods_crm_lead_data_day l "
        "WHERE NULLIF(TRIM(l.`客户单位`), '') IS NOT NULL "
        "  AND l.`线索获得日期` IS NOT NULL"
    )
    with engine.begin() as conn:
        result = conn.execute(sql, {"batch_id": batch_id})
        inserted = result.rowcount
    logger.info("  CRM leads → interaction_detail_temp: %d rows (incremental)", inserted)
    return inserted


def _incremental_load_crm_opportunity(batch_id: int) -> int:
    """增量同步：整表重跑 CRM 商机（全量模式），靠 (source_table, source_id) 唯一键去重。

    contact_name ← 业务机会所有人名称（商机联系人/负责人）；mobile 商机表无对应字段置空。
    """
    engine = get_etl_engine()
    sql = text(
        "INSERT IGNORE INTO dws_interaction_detail_temp "
        "  (customer_name, contact_name, mobile, source_table, "
        "   channel, behavior_type, content, event_time, source_id, etl_time, sync_batch_id) "
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
        "  NOW(), :batch_id "
        "FROM ods_crm_opportunity_data_day o "
        "WHERE NULLIF(TRIM(o.`客户名`), '') IS NOT NULL "
        "  AND o.`创建日期-转化` IS NOT NULL"
    )
    with engine.begin() as conn:
        result = conn.execute(sql, {"batch_id": batch_id})
        inserted = result.rowcount
    logger.info("  CRM opportunities → interaction_detail_temp: %d rows (incremental)", inserted)
    return inserted
