"""DWS 聚合表查询索引的「缺失即补齐」维护模块。

背景
----
``dws_*`` 聚合表每天被 ETL 全量重建（双表轮转：主表 DROP/重建），
其上所有二级索引随之消失。若查询层（客户列表 / 筛选项 / 重客查询 /
联系人 / 互动）依赖这些索引，重建后会出现全表扫描，在 ETL 高负载窗口
极易触发 ``(2013, 'Lost connection ...')`` 等连接失活（典型如
``get_filter_options`` 的 ``campaign_tag`` 全表扫描）。

为此本模块集中声明 DWS 表「应为查询提速」的索引清单，并提供
``ensure_dws_indexes()``：
- 应用启动时（``main.py`` lifespan）调用一次，作为兜底；
- ETL 全量同步完成后（``pipeline.run_full_sync``）调用一次，使索引在
  每日重建后持续存在。

每个索引按「先查 ``information_schema`` 是否存在、缺失才 ``CREATE``」的
方式补齐；``CREATE`` 采用在线、不锁表语法（``ALGORITHM=INPLACE,
LOCK=NONE``），失败时回退为普通 ``CREATE INDEX``，避免阻塞读写。
"""
from __future__ import annotations

import logging
from typing import List, Optional

from sqlalchemy import text

from app.database import SessionLocal

logger = logging.getLogger(__name__)


# ── DWS 查询索引清单（按查询层实际 WHERE / JOIN / GROUP BY 列声明）─────────────
# 选择原则：
#   1. 被高频过滤 / 连接 / 分组的列；
#   2. 低基数列（industry/region/owner_name/purchase_stage/intent_level/attribute）
#      适合做过滤索引；
#   3. campaign_tag 做成「覆盖索引」，使 get_filter_options 的
#      ``WHERE campaign_tag IN (...) SELECT 多列`` 走纯索引扫描，彻底消除 2013 根因；
#   4. interaction 表按 (customer_name, event_time) 与 (event_time, customer_name)
#      双向覆盖「按客户拉时间线」与「按时间窗 GROUP BY customer_name」两类查询。
DWS_INDEX_SPECS: List[dict] = [
    # ── dws_customer_360：客户列表 / 筛选项 / 重客查询 的过滤列 ──
    {
        # 覆盖索引：get_filter_options 按列 DISTINCT 时，industry/region/owner_name/
        # purchase_stage/intent_level 均落在该索引内，纯索引扫描、仅返回少量 distinct 值。
        # 注意：不含 customer_name（否则 7 列 varchar 全列超 InnoDB 3072 字节上限）。
        "table": "dws_customer_360",
        "name": "idx_c360_campaign_tag",
        "columns": ["campaign_tag", "industry", "region", "owner_name",
                    "purchase_stage", "intent_level"],
        "unique": False,
    },
    {
        # campaign_tag + customer_name 覆盖：支撑「按专项拉客户名」(get_filter_options 的
        # keywords 维) 与「campaign_tag + customer_name」组合过滤，索引内纯扫描。
        "table": "dws_customer_360",
        "name": "idx_c360_campaign_tag_name",
        "columns": ["campaign_tag", "customer_name"],
        "unique": False,
    },
    {"table": "dws_customer_360", "name": "idx_c360_industry",
     "columns": ["industry"], "unique": False},
    {"table": "dws_customer_360", "name": "idx_c360_owner_name",
     "columns": ["owner_name"], "unique": False},
    {"table": "dws_customer_360", "name": "idx_c360_region",
     "columns": ["region"], "unique": False},
    {"table": "dws_customer_360", "name": "idx_c360_purchase_stage",
     "columns": ["purchase_stage"], "unique": False},
    {"table": "dws_customer_360", "name": "idx_c360_intent_level",
     "columns": ["intent_level"], "unique": False},
    {"table": "dws_customer_360", "name": "idx_c360_attribute",
     "columns": ["attribute"], "unique": False},

    # ── dws_contact_360：联系人查询按 customer_id 取合并簇 ──
    # 注：customer_id 已被既有唯一索引 uk_customer_mobile(customer_id, mobile) 的前导列覆盖，
    # 无需再建单列索引（避免每日 ETL 重复维护冗余索引），故此处不声明。

    # ── dws_interaction_detail：按客户拉时间线 / 按时间窗聚合 ──
    {"table": "dws_interaction_detail", "name": "idx_interaction_cust_event",
     "columns": ["customer_name", "event_time"], "unique": False},
    {"table": "dws_interaction_detail", "name": "idx_interaction_event_cust",
     "columns": ["event_time", "customer_name"], "unique": False},
]


def _existing_index_names(session, table: str) -> set:
    """返回指定表已有的全部索引名（含主键/唯一索引）。"""
    rows = session.execute(text(
        "SELECT INDEX_NAME FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
    ), {"t": table}).mappings().all()
    return {r["INDEX_NAME"] for r in rows}


def _create_one_index(session, spec: dict) -> None:
    """创建一个索引：依次尝试 在线不锁表 → 仅在线 → 普通 CREATE INDEX。"""
    cols = ", ".join(spec["columns"])
    unique = "UNIQUE " if spec.get("unique") else ""
    attempts = [
        f"CREATE {unique}INDEX {spec['name']} ON {spec['table']} ({cols}) "
        f"ALGORITHM=INPLACE, LOCK=NONE",
        f"CREATE {unique}INDEX {spec['name']} ON {spec['table']} ({cols}) "
        f"ALGORITHM=INPLACE",
        f"CREATE {unique}INDEX {spec['name']} ON {spec['table']} ({cols})",
    ]
    last_err: Optional[Exception] = None
    for ddl in attempts:
        try:
            session.execute(text(ddl))
            session.commit()
            return
        except Exception as e:  # 在线 DDL 不支持 / 列过长 / 并发冲突等
            last_err = e
            try:
                session.rollback()
            except Exception:
                pass
    assert last_err is not None
    raise last_err


def ensure_dws_indexes(session: Optional[object] = None) -> List[str]:
    """检测并补齐 DWS 表缺失的查询索引，返回本次新建的索引名列表。

    - ``session`` 为空时自建并关闭会话；传入会话时复用且不主动关闭（由调用方管理）。
    - 任一索引创建失败仅记录警告并继续，不影响其余索引。
    """
    own_session = session is None
    if own_session:
        session = SessionLocal()
    created: List[str] = []
    try:
        for spec in DWS_INDEX_SPECS:
            try:
                existing = _existing_index_names(session, spec["table"])
            except Exception as e:
                logger.warning("查询 %s 现有索引失败（跳过）: %s",
                               spec["table"], e)
                continue
            if spec["name"] in existing:
                continue
            try:
                _create_one_index(session, spec)
                created.append(spec["name"])
                logger.info("已补齐索引 %s ON %s (%s)",
                            spec["name"], spec["table"], ", ".join(spec["columns"]))
            except Exception as e:
                # 回滚本次失败的事务，继续处理后续索引
                try:
                    session.rollback()
                except Exception:
                    pass
                logger.warning("补齐索引 %s 失败（跳过）: %s", spec["name"], e)
    finally:
        if own_session:
            session.close()
    if created:
        logger.info("ensure_dws_indexes 完成，新建索引 %d 个: %s",
                    len(created), created)
    else:
        logger.info("ensure_dws_indexes 完成，所有 DWS 查询索引均已存在，无需新建")
    return created
