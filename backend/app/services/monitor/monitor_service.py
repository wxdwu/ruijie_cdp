"""
聚合表数据规模监控服务。

功能：
  - 统计一组“被监控表”的当前数据量（行数）
  - 每次运行把每个表的 (表名, 数据量, 运行时间) 写入观测表 dws_sync_obs（每表一条）

设计要点（可扩展性）：
  - 监控对象用「注册表 MONITOR_REGISTRY」管理，新增表只需往里加一项，
    或运行时调用 register_table(name, count_sql=None)；无需改动 run_monitor 主流程。
  - 单个表计数失败不影响其他表（容错，失败表记 -1）。
  - 观测表在首次运行时自动创建（CREATE TABLE IF NOT EXISTS），无需手动建表。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# 观测结果落库表名
OBS_TABLE = "dws_sync_obs"


def _now_cst() -> datetime:
    """返回写入 DATETIME 列的“无时区”datetime（北京时间）。

    说明：当前容器环境下 `datetime.now()` 取到的时间比北京时间快 8 小时，
    因此直接减去 8 小时得到正确的北京时间后再写入。
    """
    return datetime.now() - timedelta(hours=8)


@dataclass
class MonitoredTable:
    """一个被监控的表。

    count_sql 为可选自定义计数 SQL；留空则默认使用 `SELECT COUNT(*) FROM table_name`。
    当某张表需要“带条件的行数”（如只统计有效数据）时，可传入 count_sql。
    """

    table_name: str
    count_sql: Optional[str] = None


# 监控注册表：当前监控 dws 层聚合表 + ods 层源表。
# 后续新增表：直接在列表里追加 MonitoredTable("新表名")，或运行时调用 register_table()。
_MONITOR_REGISTRY: List[MonitoredTable] = [
    # dws 层聚合/结果表
    MonitoredTable("dws_contact_360"),
    MonitoredTable("dws_contact_mapping"),
    MonitoredTable("dws_customer_360"),
    MonitoredTable("dws_interaction_detail"),
    MonitoredTable("review_candidate"),
    # ods 层源表
    MonitoredTable("ods_zhique_behavior_list_day"),
    MonitoredTable("ods_zhique_contact_day"),
    MonitoredTable("ods_zhique_contact_detail_day"),
    MonitoredTable("ods_linkflow_contacts_day"),
    MonitoredTable("ods_linkflow_events_day"),
    MonitoredTable("ods_tianrun_customer_profile_day"),
    MonitoredTable("ods_tianrun_session_day"),
    MonitoredTable("ods_tianrun_session_detail_day"),
    MonitoredTable("ods_ruijie_website_user_day"),
    MonitoredTable("ods_crm_opportunity_data_day"),
    MonitoredTable("ods_crm_lead_data_day"),
    MonitoredTable("ods_crm_key_account_output_list_day"),
]


def get_monitored_tables() -> List[MonitoredTable]:
    """返回当前所有被监控的表（副本，避免外部直接改注册表）。"""
    return list(_MONITOR_REGISTRY)


def register_table(table_name: str, count_sql: Optional[str] = None) -> None:
    """运行时动态注册一个需要监控的表（便于后续扩展，无需改主流程）。"""
    _MONITOR_REGISTRY.append(MonitoredTable(table_name, count_sql))
    logger.info("已注册监控表: %s", table_name)


def ensure_obs_table(db: Session) -> None:
    """幂等创建观测表 dws_sync_obs（已存在则跳过）。"""
    db.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {OBS_TABLE} (
                id          BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键，自增',
                table_name  VARCHAR(128) NOT NULL                COMMENT '被监控的表名',
                table_count BIGINT       NOT NULL DEFAULT 0      COMMENT '该表当前数据量（行数）',
                create_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '监控运行时间',
                PRIMARY KEY (id),
                KEY idx_table_time (table_name, create_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用于监控聚合表数据规模'
            """
        )
    )
    db.commit()


def _count_table(db: Session, table: MonitoredTable) -> int:
    """统计单表数据量；失败容错，返回 -1 并记录日志。"""
    try:
        sql = table.count_sql or f"SELECT COUNT(*) FROM {table.table_name}"
        return int(db.execute(text(sql)).scalar() or 0)
    except Exception as exc:
        logger.warning("监控表 %s 计数失败: %s", table.table_name, exc)
        return -1


def run_monitor(db: Session) -> List[dict]:
    """执行一次完整监控：逐表计数并写入 dws_sync_obs，每表一条记录。

    返回本次写入的观测记录列表（table_name / table_count / create_at）。
    """
    ensure_obs_table(db)
    now = _now_cst()
    records: List[dict] = []

    for table in get_monitored_tables():
        count = _count_table(db, table)
        db.execute(
            text(
                f"INSERT INTO {OBS_TABLE} (table_name, table_count, create_at) "
                f"VALUES (:name, :cnt, :ts)"
            ),
            {"name": table.table_name, "cnt": count, "ts": now},
        )
        records.append(
            {
                "table_name": table.table_name,
                "table_count": count,
                "create_at": now.isoformat(timespec="seconds"),
            }
        )

    db.commit()
    logger.info("监控完成，本次写入 %d 条观测记录", len(records))
    return records


def get_latest_snapshot(db: Session) -> List[dict]:
    """返回每个表最近一次（最新）监控到的数据量快照。"""
    ensure_obs_table(db)
    rows = db.execute(
        text(
            f"""
            SELECT o.table_name, o.table_count, o.create_at
            FROM {OBS_TABLE} o
            INNER JOIN (
                SELECT table_name, MAX(id) AS max_id
                FROM {OBS_TABLE}
                GROUP BY table_name
            ) m ON m.table_name = o.table_name AND m.max_id = o.id
            ORDER BY o.table_name
            """
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def get_latest_obs(db: Session, limit: int = 100) -> List[dict]:
    """返回最近的监控历史记录（按时间倒序）。"""
    ensure_obs_table(db)
    rows = db.execute(
        text(
            f"SELECT id, table_name, table_count, create_at "
            f"FROM {OBS_TABLE} "
            f"ORDER BY create_at DESC, id DESC "
            f"LIMIT :lim"
        ),
        {"lim": limit},
    ).mappings().all()
    return [dict(r) for r in rows]
