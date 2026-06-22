"""
CDP ABM 360 – FastAPI application entry-point.

Starts the ETL scheduler on startup and shuts it down on shutdown.
Exposes a manual trigger endpoint at POST /api/admin/etl/run.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.routers import customer_list, customer_detail, ai_chat, campaign, review, sync
from app.services.etl_scheduler import start_scheduler, stop_scheduler

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


# ─────────────────────────────────────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "CDP ABM 360"}


# ─────────────────────────────────────────────────────────────────────────────
# Admin – manual ETL trigger
# ─────────────────────────────────────────────────────────────────────────────

_etl_lock = asyncio.Lock()


@app.post("/api/admin/etl/run")
async def trigger_etl():
    """Manually trigger an ETL run.

    Uses a lock to prevent overlapping runs.  Returns the ETL statistics
    dict produced by run_etl().
    """
    if _etl_lock.locked():
        raise HTTPException(
            status_code=409,
            detail="An ETL run is already in progress. Please wait.",
        )

    async with _etl_lock:
        from app.services.etl_sync import run_etl

        try:
            # Run the synchronous ETL in a thread so we don't block the event loop
            stats = await asyncio.to_thread(run_etl)
            return {"status": "ok", "stats": stats}
        except Exception as exc:
            logger.exception("Manual ETL run failed: %s", exc)
            raise HTTPException(
                status_code=500,
                detail=f"ETL run failed: {exc}",
            )
