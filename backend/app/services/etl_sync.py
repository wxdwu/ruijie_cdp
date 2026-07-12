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
import time
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config import settings
from app.connection_pool import get_engine as _get_shared_engine, execute_with_retry

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Database config – use the shared connection pool
# ─────────────────────────────────────────────────────────────────────────────


def get_etl_engine() -> Engine:
    """Return the shared connection pool engine (backward-compatible wrapper)."""
    return _get_shared_engine()


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
    """Execute a SQL statement and return rowcount.

    Write operations are automatically retried on transient errors
    (deadlocks, lock wait timeouts) using the shared connection pool.
    """
    def _do_exec() -> int:
        engine = get_etl_engine()
        with engine.begin() as conn:
            result = conn.execute(text(sql), params or {})
            return result.rowcount

    # Only retry DML (INSERT/UPDATE/DELETE/REPLACE); DDL is not safely retryable
    sql_upper = sql.strip().upper()
    is_dml = any(
        sql_upper.startswith(kw) for kw in ("INSERT", "UPDATE", "DELETE", "REPLACE")
    )
    if is_dml:
        return execute_with_retry(
            _do_exec,
            operation_name=f"DML: {sql[:100].replace('%', '%%')}",
        )
    return _do_exec()


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


def _table_count_approx(table: str) -> int:
    """Return an approximate row count from information_schema.

    Exact COUNT(*) on large InnoDB tables can take several seconds because it
    scans the clustered index.  For sync metadata we only need an approximate
    size, so we use the cardinality stored in information_schema.tables.
    """
    rows = _exec_query(
        "SELECT table_rows FROM information_schema.tables "
        "WHERE table_schema = 'app_cdp' AND table_name = :t",
        {"t": table},
    )
    return rows[0][0] if rows else 0


def _create_indexes() -> None:
    """Create indexes needed for efficient joins during ETL."""
    # Indexes on ODS tables for efficient lookups
    _ensure_index("ods_crm_contact_day", "idx_crm_mobile", "mobile")
    _ensure_index("ods_linkflow_contacts_day", "idx_lf_cid", "contact_id")
    _ensure_index("ods_linkflow_events_day", "idx_lfe_cid", "contact_id")
    _ensure_index("ods_zhique_behavior_list_day", "idx_zqb_mobile", "mobile_phone")
    _ensure_index("ods_tianrun_session_day", "idx_tr_vid", "visitor_id")

    # ── 聚合/分组提速索引 ───────────────────────────────────────────────
    # 1) CRM 两张源表按 customer_name 分组（预聚合联系人属性、商机指标）时避免全表 filesort
    _ensure_index("ods_crm_contact_day", "idx_crm_custname", "customer_name")
    _ensure_index("ods_crm_opportunity_day", "idx_opp_custname", "customer_name")
    # 2) 智渠联系人按 related_company 取 ICP 客户（DISTINCT）及按 mobile 取 ICP 手机号
    _ensure_index("ods_zhique_contact_day", "idx_zqc_related", "related_company")
    _ensure_index("ods_zhique_contact_day", "idx_zqc_mobile", "mobile")
    # 3) 天润会话按 customer_name 过滤（建 contact_mapping 与交互明细时跳过 NULL）
    _ensure_index("ods_tianrun_session_day", "idx_tr_custname", "customer_name")
    # 4) 交互明细按 (contact_name, mobile) 分组构建 dws_contact_360 时避免 filesort
    #    （增量临时表由 LIKE 主表创建，会自动继承该索引）
    _ensure_index("dws_interaction_detail", "idx_contact_mobile", "contact_name, mobile")

    # NOTE: Removed redundant/duplicate indexes:
    # - idx_cm_mobile (duplicate of idx_mobile on dws_contact_mapping)
    # - idx_cm_custname (redundant - uk_customer_mobile prefix covers customer_name)
    # - idx_cm_sync_batch (sync_batch_id not currently used)
    # - idx_id_sync_batch (sync_batch_id not currently used)
    # - idx_icp_custname (redundant - primary key covers customer_name on tmp_icp_customers)


# ─────────────────────────────────────────────────────────────────────────────
# Double Table Rotation Helpers
# ─────────────────────────────────────────────────────────────────────────────

def ensure_backup_tables() -> None:
    """Ensure backup tables exist for all DWS tables.
    
    Creates backup tables with '_backup' suffix for double table rotation.
    Backup tables have identical structure to the main tables.
    """
    dws_tables = [
        "dws_contact_mapping",
        "dws_interaction_detail",
        "dws_customer_360",
        "dws_contact_360",
    ]
    
    engine = get_etl_engine()
    
    for table in dws_tables:
        backup_table = f"{table}_backup"
        
        # Check if backup table exists
        rows = _exec_query(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'app_cdp' "
            "  AND table_name = :t "
            "LIMIT 1",
            {"t": backup_table},
        )
        
        if not rows:
            logger.info("Creating backup table %s", backup_table)
            with engine.begin() as conn:
                # Create backup table with identical structure
                conn.execute(text(f"CREATE TABLE {backup_table} LIKE {table}"))
                # NOTE: Removed idx_backup_sync_batch index creation
                # sync_batch_id field is not currently used
            logger.info("Backup table %s created successfully", backup_table)
        else:
            logger.debug("Backup table %s already exists", backup_table)


def _validate_table_data(table: str) -> Dict[str, Any]:
    """Validate data quality for a table.
    
    Performs comprehensive data quality validation:
    1. Row count validation (row_count > 0)
    2. Key field non-null validation (customer_name or contact_name is not null or empty)
    3. Data integrity validation (check for data consistency)
    
    Args:
        table: Table name to validate
        
    Returns:
        Dict with validation results:
        - valid: bool - whether validation passed
        - row_count: int - total row count
        - null_customer_count: int - count of rows with null/empty key field
        - error_message: str - error message if validation failed
    """
    result: Dict[str, Any] = {
        "valid": False,
        "row_count": 0,
        "null_customer_count": 0,
        "error_message": "",
    }
    
    try:
        # 1. Row count validation
        row_count = _table_count(table)
        result["row_count"] = row_count
        
        if row_count == 0:
            result["error_message"] = f"Validation failed: {table} has 0 rows"
            logger.error("Data validation failed for %s: row count is 0", table)
            return result
        
        logger.info("Validation passed for %s: row_count = %d", table, row_count)
        
        # 2. Key field non-null validation
        # Determine the key field name based on table
        # dws_contact_360 uses 'contact_name', others use 'customer_name'
        if table == "dws_contact_360":
            key_field = "contact_name"
        else:
            key_field = "customer_name"
        
        null_count = _count_table_rows(
            table,
            f"{key_field} IS NULL OR {key_field} = ''"
        )
        result["null_customer_count"] = null_count
        
        if null_count > 0:
            logger.warning(
                "Data quality warning for %s: %d rows have null/empty %s",
                table, null_count, key_field
            )
        
        # 3. Data integrity validation (example: check for duplicate customer_name in dws_customer_360)
        if table == "dws_customer_360":
            with get_etl_engine().connect() as conn:
                dup_result = conn.execute(text(
                    "SELECT COUNT(*) FROM ("
                    "  SELECT customer_name, COUNT(*) as cnt "
                    f"  FROM {table} "
                    "  GROUP BY customer_name "
                    "  HAVING cnt > 1"
                    ") t"
                ))
                dup_count = dup_result.fetchone()[0]
                
                if dup_count > 0:
                    logger.warning(
                        "Data quality warning for %s: %d duplicate customer_name found",
                        table, dup_count
                    )
        
        result["valid"] = True
        logger.info("Data validation passed for %s", table)
        
    except Exception as e:
        result["error_message"] = f"Validation error: {str(e)}"
        logger.exception("Data validation error for %s: %s", table, e)
    
    return result


def _rotate_tables_for_incremental(table: str) -> None:
    """Atomically rotate tables for incremental sync.
    
    Rotation logic for incremental sync (after data copied to temp table):
    1. RENAME TABLE main_table TO backup_table
    2. RENAME TABLE temp_table TO main_table
    
    This ensures atomic switching with no downtime.
    
    Args:
        table: Main table name (without _backup suffix)
    """
    backup_table = f"{table}_backup"
    temp_table = f"{table}_temp"
    
    logger.info("Rotating tables for incremental sync: %s -> %s, %s -> %s", 
                table, backup_table, temp_table, table)
    
    engine = get_etl_engine()
    
    with engine.begin() as conn:
        # Drop existing backup table if exists (safe because it contains old data)
        conn.execute(text(f"DROP TABLE IF EXISTS {backup_table}"))
        
        # Atomic table rotation using RENAME TABLE
        # MySQL RENAME TABLE is atomic
        conn.execute(text(
            f"RENAME TABLE "
            f"{table} TO {backup_table}, "
            f"{temp_table} TO {table}"
        ))
    
    logger.info("Table rotation completed: %s now points to new data", table)


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
    
    n = _exec(
        "INSERT IGNORE INTO tmp_icp_customers (customer_name) "
        "SELECT DISTINCT related_company "
        "FROM ods_zhique_contact_day "
        "WHERE related_company IS NOT NULL AND related_company != ''"
    )
    
    total = _table_count("tmp_icp_customers")
    logger.info("tmp_icp_customers built: %d ICP customers", total)
    return total


# ─────────────────────────────────────────────────────────────────────────────
# ETL-owned temporary tables (NOT ODS tables)
# ─────────────────────────────────────────────────────────────────────────────

# Names of helper tables created and dropped within each sync run.
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

    _exec("""
        INSERT IGNORE INTO tmp_icp_customers (customer_name)
        SELECT DISTINCT related_company
        FROM ods_zhique_contact_day
        WHERE related_company IS NOT NULL AND related_company != ''
    """)

    _exec("""
        INSERT IGNORE INTO tmp_icp_mobiles (mobile)
        SELECT DISTINCT mobile
        FROM ods_zhique_contact_day
        WHERE mobile IS NOT NULL AND mobile != ''
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
    is NULL for all rows.  We use visitor_id as the contact identifier and
    the contact_type_name as the channel source.  Customer names are channel
    labels rather than real company names, so we keep them for traceability.

    customer_name is not indexed on ods_tianrun_session_day; we do a single
    full pass over the ~777K-row table and keep rows with non-null names.
    """
    total_rows = _table_count("ods_tianrun_session_day")
    logger.info(
        "  Loading Tianrun sessions (single pass over %d rows)...",
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
    total_contacts = _table_count("tmp_valid_linkflow_contacts")
    logger.info(
        "  Loading Linkflow events using %d valid contacts...",
        total_contacts,
    )

    n = _exec(
        "INSERT IGNORE INTO dws_interaction_detail "
        "  (customer_name, contact_name, mobile, source_table, "
        "   channel, behavior_type, event_time, source_id, etl_time) "
        "SELECT "
        "  lc.customer_name, lc.name, lc.mobile_phone, 'linkflow', "
        "  'web', e.event_name, "
        "  FROM_UNIXTIME(e.event_date_ms / 1000), "
        "  e.event_id, NOW() "
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


# ─────────────────────────────────────────────────────────────────────────────
# Step 3: Customer 360 & Contact 360
# ─────────────────────────────────────────────────────────────────────────────

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

    # Step 2: INSERT new customers (by key_customer_name)
    n = _exec(
        "INSERT IGNORE INTO dws_customer_360 ("
        "  customer_name, owner_name, region, industry, attribute, updated_at"
        ") "
        "SELECT DISTINCT "
        "  kc.key_customer_name, "
        "  kc.customer_name, "
        "  kc.department_level3, "
        "  kc.industry_category, "
        "  kc.attribute, "
        "  NOW() "
        "FROM ods_key_customer kc "
        "WHERE kc.key_customer_name IS NOT NULL AND kc.key_customer_name != '' "
        "  AND kc.key_customer_name NOT IN ("
        "    SELECT customer_name FROM dws_customer_360"
        "  )"
    )
    logger.info("  Inserted %d new rows by key_customer_name", n)
    logger.info("Phase 5 done: ods_key_customer enriched")

    total = _table_count("dws_customer_360")
    logger.info("Customer 360 complete: %d rows", total)
    return total


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
        f"LEFT JOIN {customer_tbl} c360 ON c360.customer_name = cm.customer_name "
        "LEFT JOIN tmp_contact_interactions agg "
        "  ON agg.contact_name = cm.contact_name "
        " AND agg.mobile <=> cm.mobile "
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
        cnt = _table_count_approx(tbl)
        if tbl in ODS_INCREMENTAL_CONFIG:
            # 已配置表的水位（时间/ID）由 _set_watermark_after_load 维护，
            # 这里只刷新运行时间与行数，避免用 now 覆盖真实水位。
            _exec(
                "INSERT INTO dws_sync_meta "
                "  (table_name, last_sync_time, last_run_time, rows_synced, status) "
                "VALUES (:tbl, '1970-01-01 00:00:00', :ts, :cnt, 'success') "
                "ON DUPLICATE KEY UPDATE "
                "  last_run_time = VALUES(last_run_time), "
                "  rows_synced   = VALUES(rows_synced), "
                "  status        = 'success'",
                {"tbl": tbl, "ts": now_str, "cnt": cnt},
            )
        else:
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
        logger.info("── Step 3: Creating indexes ──")
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

        # ── 同步到 ElasticSearch（best-effort，失败不影响 ETL 主流程）──
        try:
            from app.services import es_sync
            stats["steps"]["elasticsearch"] = es_sync.sync_after_etl("full")
        except Exception as es_exc:
            logger.error("ES sync after ETL failed (best-effort): %s", es_exc)

        return stats

    except Exception as exc:
        stats["status"] = "error"
        stats["error"] = str(exc)
        logger.exception("ETL run failed: %s", exc)
        raise
"""
ETL Sync V2 Functions - Full Sync with Logging & Incremental Sync
Appended to etl_sync.py
"""

# ─────────────────────────────────────────────────────────────────────
# Schema migration – 确保 DWS 表有 sync_batch_id 字段
# ─────────────────────────────────────────────────────────────────────

def _ensure_sync_batch_column(table: str) -> None:
    """Check if sync_batch_id column exists, add if not."""
    rows = _exec_query(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = 'app_cdp' "
        "  AND table_name = :t AND column_name = 'sync_batch_id' "
        "LIMIT 1",
        {"t": table},
    )
    if not rows:
        logger.info("Adding sync_batch_id column to %s", table)
        _exec(
            f"ALTER TABLE {table} "
            "ADD COLUMN sync_batch_id BIGINT DEFAULT 0 "
            "COMMENT '同步批次ID，用于增量同步删除检测'"
        )


def _ensure_attribute_column(table: str) -> None:
    """Check if attribute column exists on dws_customer_360* tables, add if not."""
    # First verify the table actually exists (it may have been renamed away by table rotation)
    table_rows = _exec_query(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'app_cdp' "
        "  AND table_name = :t "
        "LIMIT 1",
        {"t": table},
    )
    if not table_rows:
        return

    rows = _exec_query(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = 'app_cdp' "
        "  AND table_name = :t AND column_name = 'attribute' "
        "LIMIT 1",
        {"t": table},
    )
    if not rows:
        logger.info("Adding attribute column to %s", table)
        _exec(
            f"ALTER TABLE {table} "
            "ADD COLUMN attribute VARCHAR(4) DEFAULT NULL "
            "COMMENT '客户分级 H/M/L/空'"
        )


def ensure_schema_for_incremental() -> None:
    """Ensure all DWS tables have the required fields for incremental sync."""
    tables = [
        "dws_contact_mapping",
        "dws_interaction_detail",
        "dws_customer_360",
        "dws_contact_360",
    ]
    for tbl in tables:
        _ensure_sync_batch_column(tbl)
    
    # Ensure attribute column on dws_customer_360 and its mirror tables
    for tbl in ("dws_customer_360", "dws_customer_360_temp", "dws_customer_360_backup"):
        _ensure_attribute_column(tbl)

    # 确保 ID 类字段水位列存在
    _ensure_watermark_column()

    logger.info("Schema check for incremental sync completed")


def _get_sync_batch_id() -> int:
    """Generate a new sync batch ID (Unix timestamp in milliseconds)."""
    return int(datetime.now().timestamp() * 1000)


def _get_last_sync_time(table_name: str) -> datetime | None:
    """Get the last successful sync time for a given ODS table.
    
    Returns:
        datetime object or None if no previous sync
    """
    rows = _exec_query(
        "SELECT last_sync_time FROM dws_sync_meta "
        "WHERE table_name = :tbl AND status = 'success' "
        "ORDER BY last_sync_time DESC LIMIT 1",
        {"tbl": table_name},
    )
    if rows and rows[0][0]:
        return rows[0][0]
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 数仓 ODS 表增量同步模式配置（集中管理，便于扩展新表）
#   mode="full"         ：数仓全量提供，增量同步中也整表重跑（统一全量更新）
#   mode="incremental"  ：按 field 做水位判断 已同步/未同步
#     field_type="time"      ：field 为时间字段（如 behavior_time），水位 = MAX(field)
#     field_type="unix_time" ：field 为 unix 秒（如 start_time_sec），用 FROM_UNIXTIME 比较
#     field_type="id"        ：field 为递增 ID（如 contact_id/extra_id），水位 = MAX(id)
# 仅对现有增量逻辑已涉及的表套用配置；全量/暂未接入的表仅作记录，不改逻辑。
ODS_INCREMENTAL_CONFIG: Dict[str, Dict[str, Any]] = {
    "ods_zhique_behavior_list_day":      {"mode": "incremental", "field": "behavior_time",   "field_type": "time"},
    "ods_linkflow_contacts_day":         {"mode": "incremental", "field": "contact_id",      "field_type": "id"},
    "ods_linkflow_events_day":           {"mode": "incremental", "field": "extra_id",        "field_type": "id"},
    "ods_tianrun_session_day":           {"mode": "incremental", "field": "start_time_sec",  "field_type": "unix_time"},
    # 以下为全量或暂未接入增量路径的表，仅记录便于后续扩展：
    "ods_tianrun_customer_profile_day":    {"mode": "full"},
    "ods_crm_opportunity_data_day":        {"mode": "full"},
    "ods_crm_lead_data_day":               {"mode": "full"},
    "ods_crm_key_account_output_list_day": {"mode": "full"},
    "ods_tianrun_session_detail_day":      {"mode": "incremental", "field": "start_time_sec", "field_type": "unix_time"},
    "ods_ruijie_website_user_day":         {"mode": "incremental", "field": "register_time",  "field_type": "time"},
}


def _get_last_watermark_id(table_name: str):
    """获取 ID 类字段表的上一轮最大 id 水位（dws_sync_meta.last_watermark_value）。"""
    rows = _exec_query(
        "SELECT last_watermark_value FROM dws_sync_meta "
        "WHERE table_name = :tbl AND status = 'success' "
        "ORDER BY last_run_time DESC LIMIT 1",
        {"tbl": table_name},
    )
    if rows and rows[0][0] is not None:
        return int(rows[0][0])
    return None


def _ensure_watermark_column() -> None:
    """幂等为 dws_sync_meta 增加 last_watermark_value 列（存储 ID 类字段最大 id 水位）。"""
    engine = get_etl_engine()
    with engine.connect() as conn:
        exists = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = 'app_cdp' "
                "  AND table_name = 'dws_sync_meta' "
                "  AND column_name = 'last_watermark_value' "
                "LIMIT 1"
            )
        ).fetchone()
    if not exists:
        _exec(
            "ALTER TABLE dws_sync_meta "
            "ADD COLUMN last_watermark_value BIGINT NOT NULL DEFAULT 0 "
            "COMMENT 'ID 类字段增量同步的水位：上次同步到的最大 id'"
        )
        logger.info("已为 dws_sync_meta 增加 last_watermark_value 列")


def _watermark_filter(table_name: str, alias: str):
    """返回增量过滤片段与水位值 (filter_clause, watermark_value)。

    - mode="full" 或 首次无水位 → ("", None)，调用方不加过滤（整表处理）
    - 否则返回 "AND <alias>.<field> > :watermark"（unix 时间用 FROM_UNIXTIME 包装）与水位值
    """
    cfg = ODS_INCREMENTAL_CONFIG.get(table_name)
    if cfg is None or cfg["mode"] == "full":
        return "", None

    if cfg["field_type"] == "id":
        wm = _get_last_watermark_id(table_name)
    else:
        wm = _get_last_sync_time(table_name)

    if wm is None:
        return "", None

    field = cfg["field"]
    if cfg["field_type"] == "unix_time":
        clause = f"AND FROM_UNIXTIME({alias}.{field}) > :watermark"
    else:
        clause = f"AND {alias}.{field} > :watermark"
    return clause, wm


def _set_watermark_after_load(table_name: str) -> None:
    """增量加载某表后，把当前最大水位写回 dws_sync_meta。

    时间字段 → last_sync_time（unix 时间存 FROM_UNIXTIME(MAX)）；ID 字段 → last_watermark_value。
    """
    cfg = ODS_INCREMENTAL_CONFIG.get(table_name)
    if cfg is None or cfg["mode"] == "full":
        return
    field = cfg["field"]
    if cfg["field_type"] == "id":
        _exec(
            "INSERT INTO dws_sync_meta "
            "  (table_name, last_watermark_value, last_sync_time, last_run_time, status) "
            "VALUES (:tbl, (SELECT COALESCE(MAX(" + field + "), 0) FROM " + table_name + "), '1970-01-01 00:00:00', NOW(), 'success') "
            "ON DUPLICATE KEY UPDATE "
            "  last_watermark_value = VALUES(last_watermark_value), "
            "  last_sync_time = VALUES(last_sync_time), "
            "  last_run_time = NOW(), status = 'success'",
            {"tbl": table_name},
        )
    else:
        max_expr = f"FROM_UNIXTIME(MAX({field}))" if cfg["field_type"] == "unix_time" else f"MAX({field})"
        _exec(
            "INSERT INTO dws_sync_meta "
            "  (table_name, last_sync_time, last_run_time, status) "
            "VALUES (:tbl, (SELECT COALESCE(" + max_expr + ", '1970-01-01 00:00:00') FROM " + table_name + "), NOW(), 'success') "
            "ON DUPLICATE KEY UPDATE "
            "  last_sync_time = VALUES(last_sync_time), "
            "  last_run_time = NOW(), status = 'success'",
            {"tbl": table_name},
        )


def _count_table_rows(table: str, where_clause: str = "", params: dict | None = None) -> int:
    """Count rows in a table with optional WHERE clause."""
    sql = f"SELECT COUNT(*) FROM {table}"
    if where_clause:
        sql += f" WHERE {where_clause}"
    rows = _exec_query(sql, params)
    return rows[0][0] if rows else 0


# ─────────────────────────────────────────────────────────────────────
# Sync log helpers
# ─────────────────────────────────────────────────────────────────────

def _create_sync_log(sync_type: str, trigger_by: str) -> int:
    """Create a sync log entry, return the log ID."""
    engine = get_etl_engine()
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "INSERT INTO dws_sync_log "
                "  (sync_type, trigger_by, status, start_time) "
                "VALUES (:sync_type, :trigger_by, 'running', NOW())"
            ),
            {"sync_type": sync_type, "trigger_by": trigger_by},
        )
        return result.lastrowid


def _update_sync_log(
    log_id: int,
    status: str,
    rows_synced: int = 0,
    error_message: str = "",
    details: dict | None = None,
) -> None:
    """Update a sync log entry."""
    import json
    engine = get_etl_engine()
    with engine.begin() as conn:
        if details is not None:
            try:
                details_json = json.dumps(details, ensure_ascii=False)
            except Exception as e:
                logger.error("Failed to serialize details to JSON: %s", e)
                details_json = json.dumps({"error": "Failed to serialize details"})
        else:
            details_json = None
        
        conn.execute(
            text(
                "UPDATE dws_sync_log SET "
                "  status = :status, "
                "  end_time = NOW(), "
                "  rows_synced = :rows_synced, "
                "  error_message = :error_message, "
                "  details = :details "
                "WHERE id = :log_id"
            ),
            {
                "log_id": log_id,
                "status": status,
                "rows_synced": rows_synced,
                "error_message": error_message,
                "details": details_json,
            },
        )


# ─────────────────────────────────────────────────────────────────────
# Full Sync Logic (with logging)
# ─────────────────────────────────────────────────────────────────────

def run_full_sync(trigger_by: str = "system") -> Dict[str, Any]:
    """Execute full ETL sync with logging to dws_sync_log.
    
    Uses double table rotation to ensure data availability during sync.
    """
    log_id = _create_sync_log("full", trigger_by)
    logger.info("Full sync started, log_id=%d, trigger_by=%s", log_id, trigger_by)
    
    start_time = datetime.now()
    stats: Dict[str, Any] = {
        "start_time": start_time.isoformat(),
        "steps": {},
        "status": "running",
        "log_id": log_id,
    }
    
    # Tables to rotate
    dws_tables = [
        "dws_contact_mapping",
        "dws_interaction_detail",
        "dws_customer_360",
        "dws_contact_360",
    ]
    
    try:
        # Step 0: Ensure backup tables exist
        logger.info("── Step 0: Ensuring backup tables exist ──")
        ensure_backup_tables()
        stats["steps"]["backup_tables"] = "ensured"
        
        # Step 1: Prepare backup tables for sync (swap with main tables)
        logger.info("── Step 1: Preparing backup tables for sync ──")
        engine = get_etl_engine()
        with engine.begin() as conn:
            for table in dws_tables:
                temp_table = f"{table}_temp"
                backup_table = f"{table}_backup"
                # 增量同步被中断可能遗留 *_temp 表，先清理避免 RENAME 报
                # "Table 'xxx_temp' already exists" (1050)
                conn.execute(text(f"DROP TABLE IF EXISTS {temp_table}"))
                # RENAME: main -> temp, backup -> main
                conn.execute(text(
                    f"RENAME TABLE "
                    f"{table} TO {temp_table}, "
                    f"{backup_table} TO {table}"
                ))
                logger.info("  Swapped %s with %s", table, backup_table)
        stats["steps"]["table_swap"] = "completed"
        
        # Step 2: Ensure schema for incremental sync
        t0 = _phase_start("Step 2: Ensuring schema for incremental sync")
        ensure_schema_for_incremental()
        _phase_end("Step 2: Ensuring schema for incremental sync", t0)

        # Step 3: Build ETL helper temp tables
        t0 = _phase_start("Step 3: Building ETL helper temp tables")
        _create_etl_temp_tables()
        _phase_end("Step 3: Building ETL helper temp tables", t0)

        # Step 4: Building ICP customers table
        t0 = _phase_start("Step 4: Building ICP customers table")
        icp_count = _build_icp_customers_table()
        _build_tmp_icp_filters()
        stats["steps"]["icp_customers"] = {"rows": icp_count}
        _phase_end("Step 4: Building ICP customers table", t0)

        # Step 5: Creating indexes
        t0 = _phase_start("Step 5: Creating indexes")
        _create_indexes()
        stats["steps"]["indexes"] = "created"
        _phase_end("Step 5: Creating indexes", t0)

        # Step 6: Loading contact mapping (full)
        t0 = _phase_start("Step 6: Loading contact mapping (full)")
        _build_tmp_crm_mobiles()
        _build_tmp_valid_linkflow_contacts()
        cm_stats = _load_contact_mapping()
        stats["steps"]["contact_mapping"] = cm_stats
        _phase_end("Step 6: Loading contact mapping (full)", t0)

        # Step 7: Loading interaction detail (full)
        t0 = _phase_start("Step 7: Loading interaction detail (full)")
        ix_stats = _load_interaction_detail()
        stats["steps"]["interaction_detail"] = ix_stats
        _phase_end("Step 7: Loading interaction detail (full)", t0)

        # Step 8: Building customer-360
        t0 = _phase_start("Step 8: Building customer-360")
        _build_tmp_crm_aggregates()
        c360_count = _build_customer_360()
        stats["steps"]["customer_360"] = {"rows": c360_count}
        _phase_end("Step 8: Building customer-360", t0)

        # Step 9: Building contact-360
        t0 = _phase_start("Step 9: Building contact-360")
        ct360_count = _build_contact_360()
        stats["steps"]["contact_360"] = {"rows": ct360_count}
        _phase_end("Step 9: Building contact-360", t0)

        # Step 10: Validating data quality
        t0 = _phase_start("Step 10: Validating data quality")
        validation_passed = True
        validation_details = {}
        for table in dws_tables:
            validation_result = _validate_table_data(table)
            validation_details[table] = validation_result
            if not validation_result["valid"]:
                validation_passed = False
                logger.error("Validation failed for %s: %s", table, validation_result["error_message"])

        stats["steps"]["validation"] = validation_details
        _phase_end("Step 10: Validating data quality", t0)
        
        if not validation_passed:
            # Rollback: swap back to original tables
            logger.error("Data validation failed, rolling back...")
            with engine.begin() as conn:
                for table in dws_tables:
                    temp_table = f"{table}_temp"
                    backup_table = f"{table}_backup"
                    # 清理可能残留的 backup 表，避免 RENAME 报 1050 (Table already exists)
                    conn.execute(text(f"DROP TABLE IF EXISTS {backup_table}"))
                    # RENAME: main -> backup, temp -> main (restore original)
                    conn.execute(text(
                        f"RENAME TABLE "
                        f"{table} TO {backup_table}, "
                        f"{temp_table} TO {table}"
                    ))
            raise Exception("Data validation failed, sync rolled back")
        
        # Step 10: Commit sync (rename old temp tables to backup)
        # After build, main tables already contain new data.
        # We only need to move old data (_temp) to _backup for safety.
        logger.info("── Step 10: Committing sync (atomic table rotation) ──")
        with engine.begin() as conn:
            for table in dws_tables:
                temp_table = f"{table}_temp"
                backup_table = f"{table}_backup"
                # Drop existing _backup if any, then rename _temp -> _backup
                conn.execute(text(f"DROP TABLE IF EXISTS {backup_table}"))
                conn.execute(text(f"RENAME TABLE {temp_table} TO {backup_table}"))
                logger.info("  Committed: %s stays as new data, %s archived as old data", table, backup_table)
        
        # Step 11: Updating sync metadata
        logger.info("── Step 11: Updating sync metadata ──")
        total_interaction_rows = sum(ix_stats.values())
        _update_sync_meta(total_interaction_rows)
        stats["steps"]["sync_meta"] = "updated"
        
        elapsed = (datetime.now() - start_time).total_seconds()
        stats.update({
            "status": "success",
            "end_time": datetime.now().isoformat(),
            "elapsed_seconds": round(elapsed, 2),
        })
        
        _update_sync_log(
            log_id=log_id,
            status="success",
            rows_synced=sum(cm_stats.values()) + total_interaction_rows,
            details=stats["steps"],
        )

        # ── 同步到 ElasticSearch（best-effort，失败不影响 ETL 主流程）──
        try:
            from app.services import es_sync
            stats["steps"]["elasticsearch"] = es_sync.sync_after_etl("full")
        except Exception as es_exc:
            logger.error("ES sync after full ETL failed (best-effort): %s", es_exc)

        logger.info("═══════════════════════════════════════════════════")
        logger.info(" Full sync completed in %.1f s", elapsed)
        logger.info("═══════════════════════════════════════════════════")
        return stats
        
    except Exception as exc:
        stats["status"] = "error"
        stats["error"] = str(exc)
        logger.exception("Full sync failed: %s", exc)
        
        # Try to rollback table swap if needed
        try:
            engine = get_etl_engine()
            with engine.begin() as conn:
                for table in dws_tables:
                    temp_table = f"{table}_temp"
                    backup_table = f"{table}_backup"
                    # Check if temp table exists (meaning swap happened)
                    result = conn.execute(text(
                        "SELECT 1 FROM information_schema.tables "
                        "WHERE table_schema = 'app_cdp' "
                        "  AND table_name = :t "
                        "LIMIT 1"
                    ), {"t": temp_table})
                    if result.fetchone():
                        # 清理可能残留的 backup 表，避免 RENAME 报 1050 (Table already exists)
                        conn.execute(text(f"DROP TABLE IF EXISTS {backup_table}"))
                        # RENAME: main -> backup, temp -> main (restore original)
                        conn.execute(text(
                            f"RENAME TABLE "
                            f"{table} TO {backup_table}, "
                            f"{temp_table} TO {table}"
                        ))
                        logger.info("  Rolled back table swap for %s", table)
        except Exception as rollback_exc:
            logger.error("Failed to rollback table swap: %s", rollback_exc)
        
        _update_sync_log(
            log_id=log_id,
            status="failed",
            error_message=str(exc),
            details=stats.get("steps"),
        )
        raise

    finally:
        _drop_etl_temp_tables()


# ─────────────────────────────────────────────────────────────────────
# Incremental Sync Logic
# ─────────────────────────────────────────────────────────────────────

def run_incremental_sync(trigger_by: str = "system") -> Dict[str, Any]:
    """Execute incremental ETL sync with logging to dws_sync_log.
    
    Implements true incremental sync by only processing records
    where etl_time > last_sync_time.
    
    Uses double table rotation to ensure data availability during sync.
    """
    log_id = _create_sync_log("incremental", trigger_by)
    logger.info("Incremental sync started, log_id=%d, trigger_by=%s", log_id, trigger_by)
    
    start_time = datetime.now()
    batch_id = _get_sync_batch_id()
    logger.info("Sync batch_id = %d", batch_id)
    
    stats: Dict[str, Any] = {
        "start_time": start_time.isoformat(),
        "batch_id": batch_id,
        "steps": {},
        "status": "running",
        "log_id": log_id,
    }
    
    # Tables to rotate
    dws_tables = [
        "dws_contact_mapping",
        "dws_interaction_detail",
        "dws_customer_360",
        "dws_contact_360",
    ]
    
    try:
        # Step 0: Ensure backup tables exist
        t0 = _phase_start("Step 0: Ensuring backup tables exist")
        ensure_backup_tables()
        stats["steps"]["backup_tables"] = "ensured"
        _phase_end("Step 0: Ensuring backup tables exist", t0)

        # Step 1: Prepare for table rotation
        t0 = _phase_start("Step 1: Preparing for table rotation")
        engine = get_etl_engine()
        with engine.begin() as conn:
            for table in dws_tables:
                temp_table = f"{table}_temp"
                backup_table = f"{table}_backup"

                # 重建临时表（先删除可能残留的脏表），避免上一轮中断遗留的
                # dws_xxx_temp 影响本轮增量结果（否则会在陈旧残留上累加，导致
                # dws_contact_mapping 等表数据量严重偏少）
                conn.execute(text(f"DROP TABLE IF EXISTS {temp_table}"))
                conn.execute(text(f"CREATE TABLE {temp_table} LIKE {table}"))

                # Copy existing data from main to temp (for ON DUPLICATE KEY UPDATE to work)
                # Use INSERT IGNORE to avoid duplicate primary key errors
                conn.execute(text(f"INSERT IGNORE INTO {temp_table} SELECT * FROM {table}"))
                logger.info("  Copied existing data from %s to %s", table, temp_table)
        stats["steps"]["table_swap"] = "prepared"
        _phase_end("Step 1: Preparing for table rotation", t0)

        # Step 2: Ensure schema for incremental sync
        t0 = _phase_start("Step 2: Ensuring schema for incremental sync")
        ensure_schema_for_incremental()
        _phase_end("Step 2: Ensuring schema for incremental sync", t0)

        # Step 3: Create ETL helper temp tables
        t0 = _phase_start("Step 3: Creating ETL helper temp tables")
        _create_etl_temp_tables()
        _build_tmp_icp_filters()
        _build_tmp_crm_mobiles()
        _build_tmp_valid_linkflow_contacts()
        _phase_end("Step 3: Creating ETL helper temp tables", t0)

        # Step 4: Creating indexes
        t0 = _phase_start("Step 4: Creating indexes")
        _create_indexes()
        stats["steps"]["indexes"] = "created"
        _phase_end("Step 4: Creating indexes", t0)

        # Step 5: UPSERT contact mapping (true incremental)
        t0 = _phase_start("Step 5: UPSERT contact mapping (true incremental)")
        cm_stats = _incremental_upsert_contact_mapping(batch_id)
        stats["steps"]["contact_mapping"] = cm_stats
        _phase_end("Step 5: UPSERT contact mapping (true incremental)", t0)

        # Step 5.5: Update tmp_icp_customers with new Zhique customers
        t0 = _phase_start("Step 5.5: Updating tmp_icp_customers with new Zhique customers")
        _incremental_update_icp_customers(batch_id)
        stats["steps"]["icp_customers"] = "updated"
        _phase_end("Step 5.5: Updating tmp_icp_customers with new Zhique customers", t0)

        # Step 6: UPSERT interaction detail (true incremental)
        t0 = _phase_start("Step 6: UPSERT interaction detail (true incremental)")
        ix_stats = _incremental_upsert_interaction_detail(batch_id)
        stats["steps"]["interaction_detail"] = ix_stats
        _phase_end("Step 6: UPSERT interaction detail (true incremental)", t0)

        # Rebuild aggregates if new interactions OR new contact mappings were inserted
        total_new_interactions = sum(ix_stats.values())
        total_new_contacts = sum(v for k, v in cm_stats.items() if k != "deleted")

        # Also check if there are new ICP customers
        new_icp_count = _count_table_rows(
            "tmp_icp_customers",
            "customer_name NOT IN (SELECT customer_name FROM dws_customer_360_temp)"
        )

        if total_new_interactions > 0 or total_new_contacts > 0 or new_icp_count > 0:
            t0 = _phase_start(
                f"Step 7: Rebuilding aggregates (new data: {total_new_interactions} interactions, "
                f"{total_new_contacts} contacts, {new_icp_count} new ICP)"
            )
            _build_tmp_crm_aggregates()
            agg_stats = _incremental_rebuild_aggregates(batch_id)
            stats["steps"]["aggregates"] = agg_stats
            _phase_end("Step 7: Rebuilding aggregates", t0)
        else:
            logger.info("── Step 7: Skipping aggregate rebuild (no new data) ──")
            stats["steps"]["aggregates"] = {"skipped": "no new data"}

        # Step 8: Validate data quality (same as full sync)
        t0 = _phase_start("Step 8: Validating data quality")
        validation_passed = True
        validation_details = {}
        for table in dws_tables:
            validation_result = _validate_table_data(table)
            validation_details[table] = validation_result
            if not validation_result["valid"]:
                validation_passed = False
                logger.error("Validation failed for %s: %s", table, validation_result["error_message"])

        stats["steps"]["validation"] = validation_details
        _phase_end("Step 8: Validating data quality", t0)

        if not validation_passed:
            # Rollback: swap back to original tables
            logger.error("Data validation failed, rolling back...")
            with engine.begin() as conn:
                for table in dws_tables:
                    temp_table = f"{table}_temp"
                    backup_table = f"{table}_backup"
                    # 清理可能残留的 backup 表，避免 RENAME 报 1050 (Table already exists)
                    conn.execute(text(f"DROP TABLE IF EXISTS {backup_table}"))
                    # RENAME: main -> backup, temp -> main (restore original)
                    conn.execute(text(
                        f"RENAME TABLE "
                        f"{table} TO {backup_table}, "
                        f"{temp_table} TO {table}"
                    ))
            raise Exception("Data validation failed, sync rolled back")

        # Step 9: Commit sync using atomic table rotation for incremental
        t0 = _phase_start("Step 9: Committing sync (atomic table rotation)")
        for table in dws_tables:
            _rotate_tables_for_incremental(table)
            logger.info("  Committed: %s now points to new data", table)
        _phase_end("Step 9: Committing sync (atomic table rotation)", t0)

        # Step 10: Update sync metadata
        t0 = _phase_start("Step 10: Updating sync metadata")
        total_rows = sum(v for k, v in cm_stats.items() if k != "deleted")
        total_rows += sum(ix_stats.values())
        _update_sync_meta(total_rows)
        stats["steps"]["sync_meta"] = "updated"
        _phase_end("Step 10: Updating sync metadata", t0)

        elapsed = (datetime.now() - start_time).total_seconds()
        stats.update({
            "status": "success",
            "end_time": datetime.now().isoformat(),
            "elapsed_seconds": round(elapsed, 2),
        })

        accurate_rows_synced = _calculate_accurate_rows_synced(cm_stats, ix_stats, batch_id)

        _update_sync_log(
            log_id=log_id,
            status="success",
            rows_synced=accurate_rows_synced,
            details=stats["steps"],
        )

        # ── 同步到 ElasticSearch（best-effort，失败不影响 ETL 主流程）──
        try:
            from app.services import es_sync
            stats["steps"]["elasticsearch"] = es_sync.sync_after_etl("incremental")
        except Exception as es_exc:
            logger.error("ES sync after incremental ETL failed (best-effort): %s", es_exc)

        logger.info("═══════════════════════════════════════════════════")
        logger.info(" Incremental sync completed in %.1f s", elapsed)
        logger.info(" Accurate rows_synced: %d", accurate_rows_synced)
        logger.info("═══════════════════════════════════════════════════")
        return stats

    except Exception as exc:
        stats["status"] = "error"
        stats["error"] = str(exc)
        logger.exception("Incremental sync failed: %s", exc)

        # Try to rollback table swap if needed
        try:
            engine = get_etl_engine()
            with engine.begin() as conn:
                for table in dws_tables:
                    temp_table = f"{table}_temp"
                    backup_table = f"{table}_backup"
                    # Check if temp table exists (meaning swap happened)
                    result = conn.execute(text(
                        "SELECT 1 FROM information_schema.tables "
                        "WHERE table_schema = 'app_cdp' "
                        "  AND table_name = :t "
                        "LIMIT 1"
                    ), {"t": temp_table})
                    if result.fetchone():
                        # 清理可能残留的 backup 表，避免 RENAME 报 1050 (Table already exists)
                        conn.execute(text(f"DROP TABLE IF EXISTS {backup_table}"))
                        # RENAME: main -> backup, temp -> main (restore original)
                        conn.execute(text(
                            f"RENAME TABLE "
                            f"{table} TO {backup_table}, "
                            f"{temp_table} TO {table}"
                        ))
                        logger.info("  Rolled back table swap for %s", table)
        except Exception as rollback_exc:
            logger.error("Failed to rollback table swap: %s", rollback_exc)

        _update_sync_log(
            log_id=log_id,
            status="failed",
            error_message=str(exc),
            details=stats.get("steps"),
        )
        raise

    finally:
        _drop_etl_temp_tables()


def _calculate_accurate_rows_synced(cm_stats: Dict, ix_stats: Dict, batch_id: int) -> int:
    """Calculate accurate rows_synced by querying the actual tables.
    
    Instead of relying on MySQL rowcount (which can be inaccurate for
    ON DUPLICATE KEY UPDATE), we count the actual records with the
    current sync_batch_id.
    
    Note: After table rotation, the new data is in the main tables,
    so we query the main tables to get accurate count.
    """
    engine = get_etl_engine()
    total = 0
    
    # Count contact_mapping records with this batch_id
    # After rotation, new data is in main table
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT COUNT(*) FROM dws_contact_mapping "
                "WHERE sync_batch_id = :batch_id"
            ),
            {"batch_id": batch_id}
        )
        cm_count = result.fetchone()[0]
        
        total += cm_count
        logger.info("  Accurate count: dws_contact_mapping %d records (batch_id=%d)", 
                    cm_count, batch_id)
    
    # Count interaction_detail records with this batch_id
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT COUNT(*) FROM dws_interaction_detail "
                "WHERE sync_batch_id = :batch_id"
            ),
            {"batch_id": batch_id}
        )
        ix_count = result.fetchone()[0]
        
        total += ix_count
        logger.info("  Accurate count: dws_interaction_detail %d records (batch_id=%d)", 
                    ix_count, batch_id)
    
    logger.info("  Total accurate rows_synced: %d", total)
    return total


def _get_accurate_stats_by_source(table: str, batch_id: int) -> Dict[str, int]:
    """按 source_table 分组精确统计实际影响行数。
    
    通过查询 sync_batch_id 来精确统计，避免 MySQL rowcount 不准确的问题。
    MySQL rowcount 对于 ON DUPLICATE KEY UPDATE：插入=1，更新=2，无变化=0。
    
    Args:
        table: 表名（dws_contact_mapping 或 dws_interaction_detail）
        batch_id: 当前同步批次 ID
        
    Returns:
        按 source_table 分组的统计结果，如 {"zhique": 10, "crm": 20}
    """
    engine = get_etl_engine()
    
    # 确定 source_table 字段名（dws_interaction_detail 使用 channel 或需要根据实际情况调整）
    source_field = "source_table"
    
    # Determine which table to query - use temp table for incremental sync
    # After table rotation, new data will be in main table, but this function
    # is called before rotation, so we need to check both possibilities
    tables_to_check = [table, f"{table}_temp"]
    
    stats_by_source = {}
    with engine.connect() as conn:
        for check_table in tables_to_check:
            result = conn.execute(
                text(
                    f"SELECT {source_field}, COUNT(*) as cnt "
                    f"FROM {check_table} "
                    "WHERE sync_batch_id = :batch_id "
                    f"GROUP BY {source_field}"
                ),
                {"batch_id": batch_id}
            )
            for row in result.fetchall():
                if row[0]:  # 忽略 source_table 为 NULL 的记录
                    stats_by_source[row[0]] = stats_by_source.get(row[0], 0) + row[1]
    
    logger.info("  Accurate stats for %s (batch_id=%d): %s", table, batch_id, stats_by_source)
    return stats_by_source


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
        "   channel, behavior_type, event_time, source_id, etl_time, sync_batch_id) "
        "SELECT "
        "  lc.customer_name, lc.name, lc.mobile_phone, 'linkflow', "
        "  'web', e.event_name, "
        "  FROM_UNIXTIME(e.event_date_ms / 1000), "
        "  e.event_id, NOW(), :batch_id "
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

    # Step 2: INSERT new customers (by key_customer_name)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT IGNORE INTO dws_customer_360_temp ("
                "  customer_name, owner_name, region, industry, attribute, updated_at"
                ") "
                "SELECT DISTINCT "
                "  kc.key_customer_name, "
                "  kc.customer_name, "
                "  kc.department_level3, "
                "  kc.industry_category, "
                "  kc.attribute, "
                "  NOW() "
                "FROM ods_key_customer kc "
                "WHERE kc.key_customer_name IS NOT NULL AND kc.key_customer_name != '' "
                "  AND kc.key_customer_name NOT IN ("
                "    SELECT customer_name FROM dws_customer_360_temp"
                "  )"
            )
        )

    logger.info("  customer_360 updated: %d customers (complete with Phase 1-5)", total_updated)
    return total_updated


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


def _incremental_rebuild_aggregates(batch_id: int) -> Dict[str, int]:
    """Incrementally rebuild customer_360 and contact_360 for affected customers only.
    
    Instead of full rebuild, only updates customers that have new data
    in the current sync batch.
    """
    logger.info("Incremental sync: Incrementally updating aggregate tables...")
    
    c360_count = _incremental_build_customer_360(batch_id)
    ct360_count = _incremental_build_contact_360(batch_id)
    
    return {"customer_360": c360_count, "contact_360": ct360_count}
