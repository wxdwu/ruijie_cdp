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

from app.routers import customer_list, customer_detail, ai_chat, campaign, review, sync, pool, es_sync, es_crud, monitor
from app.services.etl.etl_scheduler import start_scheduler, stop_scheduler
from app.database.engine import dispose_engine

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Lifespan – startup / shutdown hooks
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle: start scheduler on boot, stop on exit."""
    logger.info("Starting ETL scheduler …")
    start_scheduler()
    yield
    logger.info("Stopping ETL scheduler …")
    stop_scheduler()
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
app.include_router(customer_list.router)
app.include_router(customer_detail.router)
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
    return {"status": "ok", "service": "CDP ABM 360"}


# ── Demo page (prototype, no navigation entry) ──

_demo_html_path = Path(__file__).parent / "static" / "demo.html"


@app.get("/demo", response_class=HTMLResponse)
async def demo():
    """Serve the CDP MVP prototype HTML page."""
    if not _demo_html_path.exists():
        raise HTTPException(status_code=404, detail="Demo page not found")
    return _demo_html_path.read_text(encoding="utf-8")



