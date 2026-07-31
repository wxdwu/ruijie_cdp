"""ETL 定时调度器（基于 APScheduler）。

按可配置的时间点（默认每天 12:00 与 00:00，即 24:00）触发**全量同步**
run_full_sync，并在每次触发后自动写入观测表 dws_sync_obs。

设计要点：
  - 不再使用旧的 run_etl（不可审计、无双表轮换），统一走可审计的
    run_full_sync（写 dws_sync_log + 双表原子轮换）。
  - 调度时间由环境变量 ETL_FULL_SYNC_CRONS 控制，格式为逗号分隔的
    5 段 cron 表达式，例如 "0 12 * * *,0 0 * * *"（默认值）。
  - 每次定时触发除执行全量同步外，还会调用现成的 run_monitor 接口，
    将各表数据量写入 dws_sync_obs 观测表（best-effort，失败不影响同步）。
"""

import logging
import os
from typing import List

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

# 默认每天 12:00 与 00:00（即 24:00）各执行一次全量同步
DEFAULT_CRONS: List[str] = ["0 12 * * *", "0 0 * * *"]

# 调度器统一使用北京时间，避免容器 UTC 时区导致触发时刻偏移
_SCHEDULER_TIMEZONE = "Asia/Shanghai"


def _parse_crons() -> List[str]:
    """从环境变量 ETL_FULL_SYNC_CRONS 解析 cron 表达式列表，缺省用默认值。"""
    raw = os.getenv("ETL_FULL_SYNC_CRONS")
    if raw:
        crons = [c.strip() for c in raw.split(",") if c.strip()]
        if crons:
            return crons
    return list(DEFAULT_CRONS)


def _scheduled_full_sync() -> None:
    """定时任务执行体：跑一次可审计的全量同步，并写入 dws_sync_obs 观测表。"""
    from app.services.etl.full_sync.pipeline import run_full_sync
    from app.services.monitor.monitor_service import run_monitor
    from app.database import SessionLocal

    # 1) 全量同步（自带 dws_sync_log 审计 + 双表原子轮换）
    try:
        stats = run_full_sync(trigger_by="scheduler")
        status = stats.get("status") if isinstance(stats, dict) else "unknown"
        if status == "skipped":
            running = stats.get("running_sync") or {}
            logger.warning(
                "定时全量同步已跳过：当前有 %s 同步（触发人=%s）正在进行",
                running.get("type"), running.get("trigger_by"),
            )
            return
        logger.info(
            "定时全量同步完成: status=%s, elapsed=%ss",
            status,
            stats.get("elapsed_seconds"),
        )
    except Exception as exc:
        logger.exception("定时全量同步失败: %s", exc)
        return  # 同步失败不再写观测，避免误记

    # 2) 写入 dws_sync_obs（直接复用现成接口 run_monitor，best-effort）
    try:
        with SessionLocal() as db:
            run_monitor(db)
    except Exception as exc:
        logger.error(
            "写入 dws_sync_obs 观测表失败（不影响本次同步）: %s", exc
        )


def start_scheduler() -> AsyncIOScheduler:
    """创建并启动后台 ETL 调度器，按配置时间点触发全量同步。"""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        logger.warning("Scheduler already running; skipping start.")
        return _scheduler

    crons = _parse_crons()
    _scheduler = AsyncIOScheduler(
        job_defaults={
            "coalesce": True,          # 错过的多次合并为一次
            "max_instances": 1,        # 同一任务不重叠
            "misfire_grace_time": 300, # 5 分钟宽限
        },
    )

    for idx, expr in enumerate(crons):
        _scheduler.add_job(
            _scheduled_full_sync,
            trigger=CronTrigger.from_crontab(expr, timezone=_SCHEDULER_TIMEZONE),
            id=f"etl_full_sync_{idx}",
            name=f"Full ETL sync at cron '{expr}'",
            replace_existing=True,
        )
        logger.info("已注册定时全量同步任务: cron=%s (时区=%s)", expr, _SCHEDULER_TIMEZONE)

    _scheduler.start()
    logger.info(
        "ETL scheduler started – %d 个定时全量同步任务已注册。", len(crons)
    )
    return _scheduler


def stop_scheduler() -> None:
    """优雅关闭调度器。"""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("ETL scheduler stopped.")
    _scheduler = None
