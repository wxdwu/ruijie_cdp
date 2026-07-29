"""
CDP ABM 360 – FastAPI application entry-point.

Starts the ETL scheduler on startup and shuts it down on shutdown.
Exposes a manual trigger endpoint at POST /api/admin/etl/run.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.routers import customer, ai_chat, campaign, review, sync, pool, es_sync, es_crud, monitor
from app.services.etl.etl_scheduler import start_scheduler, stop_scheduler
from app.database.engine import dispose_engine
from app.cache import (
    campaign_cache_coordinator,
    close_cache_client,
    get_cache_status,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Lifespan – startup / shutdown hooks
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle: start scheduler on boot, stop on exit."""
    logger.info("Starting ETL scheduler …")
    start_scheduler()
    logger.info("Scheduling campaign cache warm-up …")
    campaign_cache_coordinator.schedule_startup_warm()
    try:
        # 确保公司合并持久化表存在（查询层按 company_merge_map 折叠别名）
        try:
            from app.services.company_dedup.company_merge import ensure_merge_map_table
            from app.database import SessionLocal

            with SessionLocal() as _db:
                ensure_merge_map_table(_db)
            logger.info("company_merge_map 表已就绪")
        except Exception as _e:
            logger.warning("company_merge_map 初始化失败，将在首次使用时自动创建: %s", _e)

        # 启动自愈：把 review_candidate 中 status='auto_merged' 但漏写
        # company_merge_map 的候选对补同步，使「自动合并」真正落库、详情页能折叠。
        # 历史去重运行中「标记了自动合并却没真正合并」的缺口即源于此（sync 仅在
        # 全量去重 run_deduplication_background 内被调用，若那次运行中断 / 个别
        # record_merge 被跳过，缺口会永久残留）。此处每次启动幂等补同步一次，
        # 兜底修复存量缺口并防止复发。
        # 注意：放到后台线程执行，避免大量 auto_merged 行在同步时触发 MySQL 死锁
        # 重试而阻塞 lifespan、导致服务迟迟不监听端口。自愈在后台跑，不影响启动。
        try:
            import threading

            from app.services.company_dedup.company_merge import sync_auto_merged_to_map

            def _run_self_heal() -> None:
                try:
                    healed = sync_auto_merged_to_map()
                    logger.info(
                        "自动合并缺口自愈完成，本次补同步 %s 个候选对进 company_merge_map", healed
                    )
                except Exception as _e:
                    logger.warning(
                        "自动合并缺口自愈失败（不影响启动，下次启动或 "
                        "POST /api/review/sync-auto-merge 再补）: %s",
                        _e,
                    )

            _heal_thread = threading.Thread(target=_run_self_heal, name="auto-merge-selfheal", daemon=True)
            _heal_thread.start()
            logger.info("自动合并缺口自愈已在后台线程启动")
        except Exception as _e:
            logger.warning("自动合并缺口自愈线程启动失败（不影响启动）: %s", _e)

        # 确保 DWS 聚合表查询索引存在（ETL 每日重建后兜底，避免全表扫描导致连接失活）
        try:
            from app.database.dws_indexes import ensure_dws_indexes

            ensure_dws_indexes()
            logger.info("DWS 聚合表查询索引已就绪")
        except Exception as _e:
            logger.warning("DWS 索引初始化失败，将在 ETL 全量同步后自动补齐: %s", _e)

        yield
    finally:
        logger.info("Stopping ETL scheduler …")
        stop_scheduler()
        logger.info("Stopping campaign cache warm-up …")
        campaign_cache_coordinator.stop()
        logger.info("Closing cache client …")
        close_cache_client()
        logger.info("Disposing connection pool …")
        dispose_engine()


# ─────────────────────────────────────────────────────────────────────────────
# Application
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="CDP ABM 360 API",
    description="CDP ABM 360 Backend Service",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware — allow all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(customer.router)
app.include_router(ai_chat.router)
app.include_router(campaign.router)
app.include_router(review.router)
app.include_router(sync.router)
app.include_router(pool.router)
app.include_router(es_sync.router)
app.include_router(es_crud.router)
app.include_router(monitor.router)


# ─────────────────────────────────────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "service": "CDP ABM 360",
        "cache": get_cache_status(),
        "campaign_cache": campaign_cache_coordinator.get_status(),
    }


# ── Demo page (prototype, no navigation entry) ──

_demo_html_path = Path(__file__).parent / "static" / "demo.html"


@app.get("/demo", response_class=HTMLResponse)
async def demo():
    """Serve the CDP MVP prototype HTML page."""
    if not _demo_html_path.exists():
        raise HTTPException(status_code=404, detail="Demo page not found")
    return _demo_html_path.read_text(encoding="utf-8")

