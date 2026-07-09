"""monitor 包：聚合表数据规模监控。"""
from app.services.monitor.monitor_service import (
    get_latest_obs,
    get_latest_snapshot,
    get_monitored_tables,
    register_table,
    run_monitor,
)

__all__ = [
    "get_monitored_tables",
    "register_table",
    "run_monitor",
    "get_latest_obs",
    "get_latest_snapshot",
]
