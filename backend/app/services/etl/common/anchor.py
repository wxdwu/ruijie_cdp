"""ETL 共享底层模块（common/anchor.py）。

本文件从原 etl_sync.py 抽取，SQL 与调用语义保持不变，仅供 full_sync / incremental_sync 通过 `from app.services.etl.common import *` 复用。"""

from __future__ import annotations

import logging
import time

from app.services.etl.common.db import get_etl_engine, _exec, _table_count
from app.services.etl.common.zhique_detail_clean import (
    read_filtered_zhique_detail_companies,
    read_filtered_companies_from,
    bulk_insert_companies_into_tmp_icp,
)

logger = logging.getLogger(__name__)



# 以下函数/常量由原 etl_sync.py 抽取，SQL 与调用语义保持不变
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
    
    # 智渠联系人（ods_zhique_contact_day.related_company）：先按公司名规则过滤再写入
    companies = read_filtered_companies_from("ods_zhique_contact_day", "related_company")
    bulk_insert_companies_into_tmp_icp(companies)

    # 智渠联系人明细（整理表）：更全面，追加其关联公司作为 ICP 客户（先过滤非公司名）
    companies = read_filtered_zhique_detail_companies()
    bulk_insert_companies_into_tmp_icp(companies)

    total = _table_count("tmp_icp_customers")
    logger.info("tmp_icp_customers built: %d ICP customers", total)
    return total


_ETL_TEMP_TABLES = [
    "tmp_icp_mobiles",
    "tmp_crm_mobiles",
    "tmp_valid_linkflow_contacts",
    "tmp_crm_contact_attr",
    "tmp_crm_opportunity_agg",
    "tmp_contact_interactions",
]


def _drop_etl_temp_tables() -> None:
    """Drop all ETL-owned helper temp tables. Safe to call repeatedly."""
    for tbl in _ETL_TEMP_TABLES:
        try:
            _exec(f"DROP TABLE IF EXISTS {tbl}")
            logger.debug("Dropped temp table %s", tbl)
        except Exception:
            logger.exception("Failed to drop temp table %s", tbl)


def _create_etl_temp_tables() -> None:
    """Create indexed helper tables used during sync.

    These are ETL-owned tables (not ODS), created at the start of each run
    and dropped in a finally block.  They let us drive large ODS table scans
    through existing indexes instead of scanning by unfiltered id ranges.
    """
    _drop_etl_temp_tables()

    _exec("""
        CREATE TABLE tmp_icp_mobiles (
            mobile VARCHAR(255) NOT NULL PRIMARY KEY
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """)

    _exec("""
        CREATE TABLE tmp_crm_mobiles (
            mobile VARCHAR(255) NOT NULL PRIMARY KEY
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """)

    _exec("""
        CREATE TABLE tmp_valid_linkflow_contacts (
            contact_id VARCHAR(255) NOT NULL PRIMARY KEY,
            mobile_phone VARCHAR(255),
            name VARCHAR(255),
            customer_name VARCHAR(255),
            INDEX idx_mobile (mobile_phone)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """)

    _exec("""
        CREATE TABLE tmp_crm_contact_attr (
            customer_name VARCHAR(255) NOT NULL PRIMARY KEY,
            industry VARCHAR(255),
            region VARCHAR(255),
            owner_name VARCHAR(255),
            attribute VARCHAR(4),
            contact_count INT,
            mobile_count INT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """)

    _exec("""
        CREATE TABLE tmp_crm_opportunity_agg (
            customer_name VARCHAR(255) NOT NULL PRIMARY KEY,
            purchase_stage VARCHAR(255),
            forecast_type VARCHAR(255),
            active_opp_count INT,
            active_opp_amount DECIMAL(22, 2),
            funnel_opp_count INT,
            won_amount DECIMAL(22, 2)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """)

    _exec("""
        CREATE TABLE tmp_contact_interactions (
            contact_name VARCHAR(128) NOT NULL,
            mobile VARCHAR(64) DEFAULT NULL,
            interaction_count INT NOT NULL DEFAULT 0,
            interaction_count_30d INT NOT NULL DEFAULT 0,
            last_interaction_time DATETIME DEFAULT NULL,
            UNIQUE KEY uk_contact_mobile (contact_name, mobile)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """)

    logger.info("ETL helper temp tables created")


def _build_tmp_icp_filters() -> None:
    """Populate ICP company/mobile filters from the anchor table.

    统一使用持久锚点表 tmp_icp_customers（与 _build_icp_customers_table 同源），
    不再维护冗余的 tmp_icp_companies 表。
    """
    # 确保锚点表存在（增量同步路径不会调用 _build_icp_customers_table，需自建）
    _exec("""
        CREATE TABLE IF NOT EXISTS tmp_icp_customers (
            customer_name VARCHAR(255) NOT NULL PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """)
    _exec("TRUNCATE TABLE tmp_icp_customers")
    _exec("TRUNCATE TABLE tmp_icp_mobiles")

    # 智渠联系人（ods_zhique_contact_day.related_company）：先按公司名规则过滤再写入
    companies = read_filtered_companies_from("ods_zhique_contact_day", "related_company")
    bulk_insert_companies_into_tmp_icp(companies)

    _exec("""
        INSERT IGNORE INTO tmp_icp_mobiles (mobile)
        SELECT DISTINCT mobile
        FROM ods_zhique_contact_day
        WHERE mobile IS NOT NULL AND mobile != ''
    """)

    # 智渠联系人明细（整理表）：更全面，补充 ICP 公司（先过滤非公司名）与手机号
    companies = read_filtered_zhique_detail_companies()
    bulk_insert_companies_into_tmp_icp(companies)
    _exec("""
        INSERT IGNORE INTO tmp_icp_mobiles (mobile)
        SELECT DISTINCT `手机号`
        FROM ods_zhique_contact_detail_day
        WHERE `手机号` IS NOT NULL AND `手机号` != ''
    """)

    logger.info(
        "ICP filters ready: %d companies, %d mobiles",
        _table_count("tmp_icp_customers"),
        _table_count("tmp_icp_mobiles"),
    )


def _build_tmp_crm_mobiles() -> None:
    """Populate tmp_crm_mobiles with all non-null CRM mobiles.

    Used to preserve the original Zhique behavior matching semantics:
    any behavior whose mobile_phone matches a CRM contact mobile is kept.
    """
    _exec("TRUNCATE TABLE tmp_crm_mobiles")
    _exec("""
        INSERT IGNORE INTO tmp_crm_mobiles (mobile)
        SELECT DISTINCT mobile
        FROM ods_crm_contact_day
        WHERE mobile IS NOT NULL AND mobile != ''
          AND customer_name IS NOT NULL AND customer_name != ''
    """)
    logger.info("CRM mobiles ready: %d rows", _table_count("tmp_crm_mobiles"))


def _build_tmp_valid_linkflow_contacts() -> None:
    """Populate tmp_valid_linkflow_contacts with linkflow contacts that have a CRM match.

    Pre-joins CRM so linkflow event loading can drive from the small contact_id set
    and use the idx_lfe_cid index on ods_linkflow_events_day.
    """
    _exec("TRUNCATE TABLE tmp_valid_linkflow_contacts")
    n = _exec("""
        INSERT IGNORE INTO tmp_valid_linkflow_contacts
          (contact_id, mobile_phone, name, customer_name)
        SELECT
          l.contact_id, l.mobile_phone, l.name, crm.customer_name
        FROM ods_linkflow_contacts_day l
        INNER JOIN ods_crm_contact_day crm
          ON crm.mobile COLLATE utf8mb4_0900_ai_ci
           = l.mobile_phone COLLATE utf8mb4_0900_ai_ci
        WHERE l.mobile_phone IS NOT NULL AND l.mobile_phone != ''
          AND crm.customer_name IS NOT NULL AND crm.customer_name != ''
    """)
    logger.info("Valid linkflow contacts ready: %d rows", n)


def _build_tmp_crm_aggregates() -> None:
    """Pre-aggregate CRM contact attributes and opportunity metrics per customer."""
    _exec("TRUNCATE TABLE tmp_crm_contact_attr")
    _exec("TRUNCATE TABLE tmp_crm_opportunity_agg")

    n_attr = _exec("""
        INSERT INTO tmp_crm_contact_attr
          (customer_name, industry, region, owner_name, attribute, contact_count, mobile_count)
        SELECT
          customer_name,
          MAX(industry) AS industry,
          MAX(ruijie_region) AS region,
          MAX(sales_name) AS owner_name,
          MAX(attribute) AS attribute,
          COUNT(DISTINCT contact_name) AS contact_count,
          COUNT(DISTINCT CASE WHEN mobile IS NOT NULL AND mobile != ''
              THEN mobile END) AS mobile_count
        FROM ods_crm_contact_day
        WHERE customer_name IS NOT NULL AND customer_name != ''
        GROUP BY customer_name
    """)

    n_opp = _exec("""
        INSERT INTO tmp_crm_opportunity_agg
          (customer_name, purchase_stage, forecast_type, active_opp_count,
           active_opp_amount, funnel_opp_count, won_amount)
        SELECT
          customer_name,
          MAX(customer_stage) AS purchase_stage,
          MAX(forecast_type) AS forecast_type,
          COUNT(CASE WHEN is_active = 1 THEN 1 END) AS active_opp_count,
          COALESCE(SUM(CASE WHEN is_active = 1
              THEN amount_10k * 10000 ELSE 0 END), 0) AS active_opp_amount,
          COUNT(CASE WHEN is_funnel = '是' THEN 1 END) AS funnel_opp_count,
          COALESCE(SUM(actual_order_amount_10k * 10000), 0) AS won_amount
        FROM ods_crm_opportunity_day
        WHERE customer_name IS NOT NULL AND customer_name != ''
        GROUP BY customer_name
    """)

    logger.info(
        "CRM aggregates ready: %d contact attrs, %d opportunity attrs",
        n_attr, n_opp,
    )


def _phase_start(phase: str) -> float:
    """Log phase start and return timestamp for elapsed calculation."""
    logger.info("── %s ──", phase)
    return time.time()


def _phase_end(phase: str, start_ts: float) -> None:
    """Log phase completion with elapsed seconds."""
    elapsed = round(time.time() - start_ts, 2)
    logger.info("── %s completed in %.2f s ──", phase, elapsed)
