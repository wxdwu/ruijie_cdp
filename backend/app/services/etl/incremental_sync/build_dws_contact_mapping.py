"""ETL 增量同步模块（incremental_sync/build_dws_contact_mapping.py）。从原 etl_sync.py 抽取，SQL 与调用语义保持不变。"""

from __future__ import annotations

import logging

from app.services.etl.common import *  # noqa: F401,F403

logger = logging.getLogger(__name__)



# 以下函数/常量由原 etl_sync.py 抽取，SQL 与调用语义保持不变
def _incremental_update_icp_customers(batch_id: int) -> int:
    """Incrementally update tmp_icp_customers with new Zhique customers.
    
    This function ensures that new customers from ods_zhique_contact_day
    are added to tmp_icp_customers, which serves as the anchor for
    building dws_customer_360.
    
    Returns:
        Number of new ICP customers added.
    """
    logger.info("Updating tmp_icp_customers with new Zhique customers...")
    
    # Get last sync time for Zhique contacts
    last_sync_zhique = _get_last_sync_time("ods_zhique_contact_day")
    
    # Build filter for new records
    filter_clause = ""
    params: Dict[str, Any] = {"batch_id": batch_id}
    
    if last_sync_zhique:
        filter_clause = "AND etl_time > :last_sync_time"
        params["last_sync_time"] = last_sync_zhique
        logger.info("  Filtering Zhique contacts after %s", last_sync_zhique)
    
    # Insert new ICP customers (INSERT IGNORE to avoid duplicates)
    n = _exec(
        "INSERT IGNORE INTO tmp_icp_customers (customer_name) "
        "SELECT DISTINCT related_company "
        "FROM ods_zhique_contact_day "
        "WHERE related_company IS NOT NULL AND related_company != '' "
        f"  {filter_clause}",
        params
    )

    # 智渠联系人明细（整理表）：追加其新增关联公司为 ICP 客户（按 time 水位增量）
    last_sync_detail = _get_last_sync_time("ods_zhique_contact_detail_day")
    detail_filter = ""
    detail_params: Dict[str, Any] = {"batch_id": batch_id}
    if last_sync_detail:
        detail_filter = "AND `time` > :last_sync_time"
        detail_params["last_sync_time"] = last_sync_detail
    n_detail = _exec(
        "INSERT IGNORE INTO tmp_icp_customers (customer_name) "
        "SELECT DISTINCT `关联公司` "
        "FROM ods_zhique_contact_detail_day "
        "WHERE `关联公司` IS NOT NULL AND `关联公司` != '' "
        f"  {detail_filter}",
        detail_params
    )
    n += n_detail

    total = _table_count("tmp_icp_customers")
    logger.info("tmp_icp_customers updated: %d new customers, %d total", n, total)
    return n


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
    # 注：ods_linkflow_contacts_day / ods_tianrun_session_day 的增量水位由配置驱动，见 _watermark_filter

    # Debug: log last sync times
    logger.info("Last sync times:")
    logger.info("  zhique: %s", last_sync_zhique)
    logger.info("  crm: %s", last_sync_crm)
    logger.info("  marketing: %s", last_sync_marketing)
    
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
        INSERT INTO dws_contact_mapping_temp 
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
        "INSERT INTO dws_contact_mapping_temp "
        "  (customer_name, contact_name, mobile, email, department, "
        "   position, purchase_role, role_category, source_table, etl_time, sync_batch_id) "
        "SELECT "
        "  c.customer_name, c.contact_name, c.mobile, c.email, c.department, "
        "  c.position, c.purchase_role, "
        f"  CASE {role_case} ELSE '未知' END, "
        "  'crm', NOW(), :batch_id "
        "FROM ods_crm_contact_day c "
        "WHERE c.customer_name IS NOT NULL AND c.customer_name != '' "
        "  AND ( "
        "    c.customer_name IN (SELECT customer_name FROM tmp_icp_customers) "
        "    OR c.mobile IN (SELECT mobile FROM tmp_icp_mobiles) "
        "  ) "
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
        "INSERT INTO dws_contact_mapping_temp "
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
    
    # Linkflow contacts - 按 contact_id 最大 ID 水位增量（配置为 id 类字段）
    linkflow_filter, _wm = _watermark_filter("ods_linkflow_contacts_day", "l")
    linkflow_params = {"batch_id": batch_id}
    if _wm is not None:
        linkflow_params["watermark"] = _wm
    
    n = _exec(
        "INSERT INTO dws_contact_mapping_temp "
        "  (customer_name, contact_name, mobile, email, "
        "   linkflow_contact_id, source_table, etl_time, sync_batch_id) "
        "SELECT "
        "  lc.customer_name, lc.name, lc.mobile_phone, l.email, "
        "  lc.contact_id, 'linkflow', NOW(), :batch_id "
        "FROM tmp_valid_linkflow_contacts lc "
        "INNER JOIN ods_linkflow_contacts_day l ON l.contact_id = lc.contact_id "
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
    _set_watermark_after_load("ods_linkflow_contacts_day")
    
    # Tianrun contacts - 按 start_time_sec（unix 秒）水位增量
    tianrun_filter, _wm = _watermark_filter("ods_tianrun_session_day", "s")
    tianrun_params = {"batch_id": batch_id}
    if _wm is not None:
        tianrun_params["watermark"] = _wm
    
    n = _exec(
        "INSERT INTO dws_contact_mapping_temp "
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
    _set_watermark_after_load("ods_tianrun_session_day")

    # Zhique contacts (detail / 整理表)：与 zhique 同口径，数据源改为 ods_zhique_contact_detail_day。
    # 列映射：关联公司→customer_name, 姓名→contact_name, 手机号→mobile, 邮箱→email,
    # 部门→department, 职务→position。按 time 字段水位增量，仅处理新/更新记录。
    detail_filter, _wm = _watermark_filter("ods_zhique_contact_detail_day", "d")
    read_params = {}
    if _wm is not None:
        read_params["watermark"] = _wm
    # 先按 关联公司 + 姓名 过滤，再按水位读取并 upsert 进 contact_mapping_temp
    rows = read_filtered_zhique_detail_contacts(detail_filter, read_params)
    n = bulk_write_contact_mapping(
        rows, target_table="dws_contact_mapping_temp", sync_batch_id=batch_id
    )
    stats["zhique_detail"] = n
    logger.info("  Zhique (detail): %d records upserted (incremental)", n)
    _set_watermark_after_load("ods_zhique_contact_detail_day")

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
