"""ETL 增量同步模块（incremental_sync/pipeline.py）。从原 etl_sync.py 抽取，SQL 与调用语义保持不变。"""

from __future__ import annotations

import logging
from datetime import datetime
from sqlalchemy import text

from app.services.etl.common import *  # noqa: F401,F403
from app.services.etl.cache_refresh import schedule_campaign_cache_refresh
from app.services.etl.incremental_sync.build_dws_contact_mapping import (
    _incremental_upsert_contact_mapping, _incremental_update_icp_customers)
from app.services.etl.incremental_sync.build_dws_interaction_detail import (
    _incremental_upsert_interaction_detail)
from app.services.etl.incremental_sync.build_dws_customer_360 import (
    _incremental_rebuild_aggregates)

logger = logging.getLogger(__name__)



# 以下函数/常量由原 etl_sync.py 抽取，SQL 与调用语义保持不变
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

        # Step 0.5: 轮转重建 _temp 表（CREATE ... LIKE 主表）前，先确保主表与
        # 备份表含 interaction_content 列，避免后续 swap 后主表缺该字段。
        logger.info("── Step 0.5: Ensuring interaction_content column on detail tables ──")
        _ensure_interaction_content_column()

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
        # 仅在增量数据完成原子轮换并记录成功后，安排下一营销缓存 generation。
        stats["steps"]["campaign_cache_refresh"] = {
            "scheduled": schedule_campaign_cache_refresh("incremental")
        }

        # ── 同步到 ElasticSearch（best-effort，失败不影响 ETL 主流程）──
        try:
            from app.services.elasticSearch import es_sync
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
