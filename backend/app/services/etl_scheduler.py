"""
APScheduler-based ETL scheduler.

Runs run_etl() every hour via AsyncIOScheduler.
"""

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def start_scheduler() -> AsyncIOScheduler:
    """Create and start the background ETL scheduler.

    Adds a job that calls run_etl() every 1 hour.
    """
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        logger.warning("Scheduler already running; skipping start.")
        return _scheduler

    from app.services.etl_sync import run_etl

    _scheduler = AsyncIOScheduler(
        job_defaults={
            "coalesce": True,          # collapse missed runs into one
            "max_instances": 1,        # never overlap
            "misfire_grace_time": 300, # 5 min grace period
        },
    )

    _scheduler.add_job(
        run_etl,
        trigger=IntervalTrigger(hours=1),
        id="etl_hourly",
        name="Hourly ETL sync",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("ETL scheduler started – job 'etl_hourly' fires every 1 h.")
    return _scheduler


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("ETL scheduler stopped.")
    _scheduler = None
