"""ETL 与页面缓存之间的轻量、best-effort 通知边界。"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def schedule_campaign_cache_refresh(sync_type: str) -> bool:
    """在 ETL 已成功提交后安排下一 generation，失败不反向影响 ETL。"""
    try:
        # 延迟导入避免 ETL 模块加载时建立 Redis/营销服务依赖环。
        from app.cache.campaign_cache import campaign_cache_coordinator

        scheduled = campaign_cache_coordinator.schedule_generation_refresh(
            reason=f"etl-{sync_type}-success"
        )
        logger.info(
            "campaign_cache refresh_notified sync_type=%s scheduled=%s",
            sync_type,
            str(scheduled).lower(),
        )
        return scheduled
    except Exception as exc:
        logger.error(
            "campaign_cache refresh_notify_failed sync_type=%s error=%s",
            sync_type,
            exc,
        )
        return False
