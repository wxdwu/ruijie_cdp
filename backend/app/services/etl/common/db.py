"""ETL 共享底层模块（common/db.py）。

本文件从原 etl_sync.py 抽取，SQL 与调用语义保持不变，仅供 full_sync / incremental_sync 通过 `from app.services.etl.common import *` 复用。"""

from __future__ import annotations

import logging
from sqlalchemy import text

from app.database.engine import get_engine as _get_shared_engine, execute_with_retry

logger = logging.getLogger(__name__)



# 以下函数/常量由原 etl_sync.py 抽取，SQL 与调用语义保持不变
def get_etl_engine() -> Engine:
    """Return the shared connection pool engine (backward-compatible wrapper)."""
    return _get_shared_engine()


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
    # 2b) 智渠联系人明细（整理表）按 关联公司 / 手机号 取 ICP 客户与手机号
    _ensure_index("ods_zhique_contact_detail_day", "idx_zqcd_company", "`关联公司`(191)")
    _ensure_index("ods_zhique_contact_detail_day", "idx_zqcd_mobile", "`手机号`(191)")
    # 3) 天润会话按 customer_name 过滤（建 contact_mapping 与交互明细时跳过 NULL）
    _ensure_index("ods_tianrun_session_day", "idx_tr_custname", "customer_name")
    # 4) 交互明细按 (contact_name, mobile) 分组构建 dws_contact_360 时避免 filesort
    #    （增量临时表由 LIKE 主表创建，会自动继承该索引）
    _ensure_index("dws_interaction_detail", "idx_contact_mobile", "contact_name, mobile")


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


def _ensure_interaction_content_column() -> None:
    """确保 dws_interaction_detail 及其轮转镜像表（_backup / _temp）均含
    interaction_content 列。

    该列存放 Linkflow 行为来源搜索词，取自 ods_linkflow_events_day.props_json
    的 s_term 字段。全量/增量同步在轮转 swap 之前与本写入前都会调用本函数：
    列已存在则跳过；缺失则 ALTER ADD。这样无论轮转把哪张表变为主表
    （主表可能来自更早、尚不含该列的 _backup 快照），目标表结构都正确，
    不会出现“同步后字段丢失”的问题。

    健壮性：仅对实际存在的表做 ALTER；若 _backup 尚不存在（例如上一轮同步
    异常中断导致备份表被重命名/清理），则先按主表结构创建（主表此时已含该列，
    新备份表自然继承），避免对不存在的表执行 ALTER 报
    “Table '..._backup' doesn't exist”。
    """
    engine = get_etl_engine()

    def _tbl_exists(conn, name: str) -> bool:
        # 用 SHOW TABLES（基于当前连接默认库，与下方 ALTER/DDL 的库判定一致），
        # 避免 information_schema 在个别环境下对刚创建的表判定不准。
        rows = conn.execute(text("SHOW TABLES LIKE :n"), {"n": name}).fetchall()
        return bool(rows)

    def _col_exists_for(conn, tbl: str) -> bool:
        # SHOW COLUMNS 基于当前连接默认库，与 ALTER 同源，判定最可靠。
        rows = conn.execute(
            text("SHOW COLUMNS FROM " + tbl + " LIKE :c"),
            {"c": "interaction_content"},
        ).fetchall()
        return bool(rows)

    def _ensure_col(conn, tbl: str) -> None:
        if not _col_exists_for(conn, tbl):
            try:
                _exec(
                    "ALTER TABLE " + tbl + " "
                    "ADD COLUMN interaction_content VARCHAR(100) NULL "
                    "COMMENT 'Linkflow 行为来源搜索词（props_json->s_term）' "
                    "AFTER content"
                )
                logger.info("已为 %s 增加 interaction_content 列", tbl)
            except Exception as e:  # noqa: BLE001
                err = str(e)
                if "1060" in err or "1146" in err:
                    logger.info(
                        "为 %s 增加 interaction_content 列时忽略已存在/表缺失：%s",
                        tbl, err
                    )
                    return
                raise

    with engine.connect() as conn:
        # 1) 主表优先：确保含该列（后续 _backup 按主表结构创建时可继承）
        if _tbl_exists(conn, "dws_interaction_detail"):
            _ensure_col(conn, "dws_interaction_detail")
        else:
            logger.warning(
                "主表 dws_interaction_detail 不存在，跳过 interaction_content 字段确保"
            )
            return

        # 2) 备份表：不存在则先按主表结构创建（继承已含的该列），再确保列存在
        if not _tbl_exists(conn, "dws_interaction_detail_backup"):
            _exec(
                "CREATE TABLE dws_interaction_detail_backup "
                "LIKE dws_interaction_detail"
            )
            logger.info("已按主表结构创建备份表 dws_interaction_detail_backup")
        _ensure_col(conn, "dws_interaction_detail_backup")

        # 3) 增量临时表（若存在则确保列存在）
        if _tbl_exists(conn, "dws_interaction_detail_temp"):
            _ensure_col(conn, "dws_interaction_detail_temp")


def _count_table_rows(table: str, where_clause: str = "", params: dict | None = None) -> int:
    """Count rows in a table with optional WHERE clause."""
    sql = f"SELECT COUNT(*) FROM {table}"
    if where_clause:
        sql += f" WHERE {where_clause}"
    rows = _exec_query(sql, params)
    return rows[0][0] if rows else 0
