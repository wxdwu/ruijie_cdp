"""ETL 全量同步模块（full_sync/pipeline.py）。从原 etl_sync.py 抽取，SQL 与调用语义保持不变。"""

from __future__ import annotations

import logging
from datetime import datetime
from sqlalchemy import text

from app.services.etl.common import *  # noqa: F401,F403
from app.services.etl.cache_refresh import schedule_campaign_cache_refresh
from app.services.etl.full_sync.build_dws_contact_mapping import _load_contact_mapping
from app.services.etl.full_sync.build_dws_interaction_detail import _load_interaction_detail
from app.services.etl.full_sync.build_dws_customer_360 import _build_customer_360
from app.services.etl.full_sync.build_dws_contact_360 import _build_contact_360
from app.services.etl.common.interaction_align import align_interaction_detail_names
from app.services.etl.sync_lock import try_begin_sync, end_sync

logger = logging.getLogger(__name__)


# 上游 ODS 就绪校验依赖的源表清单：全量同步锚点(tmp_icp_customers)与下游构建
# 所依赖的关键 ODS 源。这些表若在定时触发窗口被上游清空，会导致数据全空。
_UPSTREAM_SOURCE_TABLES = [
    "ods_zhique_contact_detail_day",
    "ods_crm_contact_day",
    "ods_linkflow_events_day",
    "ods_tianrun_session_day",
]


def _check_upstream_ready(icp_count: int) -> None:
    """上游数据就绪校验（fail-fast）。

    全量同步几乎所有下游表都依赖 Step 4 构建的锚点表 tmp_icp_customers。若上游
    ODS 源表在定时触发窗口（如每天 12:00/00:00）正处于清空/重建，tmp_icp_customers
    会为空，导致后续 contact_mapping / interaction_detail / contact_360 全部 0 行，
    最终在 Step 10 校验失败回滚。此处提前熔断，给出明确错误，避免空跑几十分钟。

    Args:
        icp_count: Step 4 构建的 tmp_icp_customers 行数。

    Raises:
        RuntimeError: 锚点表为空或关键上游源表为空时，明确提示上游未就绪。
    """
    if icp_count <= 0:
        raise RuntimeError(
            "上游数据尚未就绪：锚点表 tmp_icp_customers 行数为 0"
            "（通常因上游 ODS 源表在定时窗口被清空/重建）。"
            "请等待上游数据就绪后重试。"
        )
    # 校验关键上游源表非空，避免更隐蔽的空数据来源
    empty_sources = []
    for src in _UPSTREAM_SOURCE_TABLES:
        try:
            cnt = _table_count(src)
        except Exception:
            # 表不存在等异常不阻断，交给正式流程报错，这里只关心“明确为空”的情况
            continue
        if cnt <= 0:
            empty_sources.append(src)
    if empty_sources:
        raise RuntimeError(
            "上游数据尚未就绪：以下关键 ODS 源表行数为 0：%s。"
            "可能正处于上游清空/重建窗口，请稍后重试。"
            % ", ".join(empty_sources)
        )
    logger.info("上游数据就绪校验通过（icp_count=%d）", icp_count)



# 全量同步编排入口（由原 etl_sync.py 抽取，SQL 与调用语义保持不变，仅保留可审计版本）




def run_full_sync(trigger_by: str = "system") -> Dict[str, Any]:
    """Execute full ETL sync with logging to dws_sync_log.
    
    Uses double table rotation to ensure data availability during sync.
    """
    # 进程级互斥：全量/增量/定时同步任一时刻只允许一个运行；若已有同步在跑则跳过。
    acquired, running = try_begin_sync("full", trigger_by)
    if not acquired:
        logger.warning(
            "跳过全量同步：当前有 %s 同步（触发人=%s）正在进行",
            (running or {}).get("type"), (running or {}).get("trigger_by"),
        )
        return {
            "status": "skipped",
            "reason": "another_sync_running",
            "running_sync": running,
        }

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

        # Step 0.5: 轮转 swap 前，先确保互动明细表（主表 + 备份表）含
        # interaction_content 列。否则 swap 会把不含该列的旧 _backup 变为主表，
        # 导致该字段在同步后“消失”。
        logger.info("── Step 0.5: Ensuring interaction_content column on detail tables ──")
        _ensure_interaction_content_column()

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

        # Step 4.1: 上游数据就绪校验（fail-fast）
        # 定时同步常在固定 cron 点（如 12:00/00:00）触发，此时上游 ODS 源表
        # 可能正处于清空/重建窗口，导致 tmp_icp_customers 为空，进而使后续
        # contact_mapping / interaction_detail / contact_360 全部 0 行，最终在
        # Step 10 校验失败回滚。这里提前熔断，给出明确错误，避免空跑几十分钟。
        _check_upstream_ready(icp_count)

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

        # Step 8.5: 对齐互动明细 customer_name 到 customer_360 标准拼写
        # （解决多源客户名大小写 / 全半角 / 首尾空格不一致导致的聚合分裂）
        t0 = _phase_start("Step 8.5: Aligning interaction_detail names to customer_360")
        align_interaction_detail_names("dws_customer_360", "dws_interaction_detail")
        _phase_end("Step 8.5: Aligning interaction_detail names to customer_360", t0)

        # Step 9: Building contact-360
        t0 = _phase_start("Step 9: Building contact-360")
        ct360_count = _build_contact_360()
        stats["steps"]["contact_360"] = {"rows": ct360_count}
        _phase_end("Step 9: Building contact-360", t0)

        # Step 9.5: 确保 DWS 聚合表查询索引存在（ETL 每日重建后保持索引，
        # 避免重建后查询全表扫描、在批量高负载窗口触发连接失活 2013）
        t0 = _phase_start("Step 9.5: Ensuring DWS query indexes")
        try:
            from app.database.dws_indexes import ensure_dws_indexes

            created_idx = ensure_dws_indexes()
            stats["steps"]["dws_indexes"] = {"created": created_idx}
        except Exception as idx_exc:
            logger.error("确保 DWS 查询索引失败（不影响 ETL 主流程）: %s", idx_exc)
        _phase_end("Step 9.5: Ensuring DWS query indexes", t0)

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
        # 数据表已提交且审计日志已标记成功后，才构建并切换营销缓存新快照。
        stats["steps"]["campaign_cache_refresh"] = {
            "scheduled": schedule_campaign_cache_refresh("full")
        }

        # ── 同步到 ElasticSearch（best-effort，失败不影响 ETL 主流程）──
        try:
            from app.services.elasticSearch import es_sync
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
        # tmp_icp_customers 是持久锚点表（CREATE TABLE IF NOT EXISTS，不随
        # _ETL_TEMP_TABLES 清理），每次 run 结束后主动 DROP，避免上游空窗口导致
        # 残留空表误导后续排查。
        try:
            _exec("DROP TABLE IF EXISTS tmp_icp_customers")
        except Exception as drop_exc:
            logger.warning("清理 tmp_icp_customers 失败（可忽略）: %s", drop_exc)
        end_sync()
