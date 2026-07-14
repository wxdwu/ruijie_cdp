"""
ElasticSearch 同步服务

将 DWS 聚合层（MySQL）的数据同步到 ElasticSearch，用于：
  - 全文检索（客户 / 联系人 / 互动）
  - 聚合分析（意图分级、行业分布、互动趋势等）

设计要点：
  - run_es_full_sync：全量重建，使用 alias 轮换，切换瞬间对检索无感知中断
  - run_es_incremental_sync：基于 DWS 表的 updated_at / etl_time 水位做增量 upsert，
    并对客户/联系人维度做“孤儿”删除检测
  - 该模块对所有异常 best-effort：ES 同步失败不影响主 ETL 流程
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, date
from decimal import Decimal
from typing import Any, Dict, List

from elasticsearch import Elasticsearch
from elasticsearch.exceptions import NotFoundError
from elasticsearch.helpers import scan
from sqlalchemy import text

from app.config import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 表 -> 索引映射（索引名本身作为对外查询的 alias）
# ─────────────────────────────────────────────────────────────────────────────

INDEX_MAP: Dict[str, str] = {
    "dws_customer_360": f"{settings.ES_INDEX_PREFIX}customer_360",
    "dws_contact_360": f"{settings.ES_INDEX_PREFIX}contact_360",
    "dws_interaction_detail": f"{settings.ES_INDEX_PREFIX}interaction_detail",
    "dws_contact_mapping": f"{settings.ES_INDEX_PREFIX}contact_mapping",
}

# 增量同步时用于删除检测的“小表”（大表 interaction_detail 通常只增不删，跳过）
PRUNE_TABLES = {"dws_customer_360", "dws_contact_360"}

# MySQL 中存储为 JSON 文本的字段，需要解析为对象后再写入 ES
JSON_COLUMNS: Dict[str, set] = {
    "dws_customer_360": {
        "role_detail", "top_channels", "highest_stage_opp",
        "product_categories", "source_tables", "data_coverage",
    },
    "dws_contact_360": {"top_content_types", "product_interests", "source_tables"},
}

# MySQL 中以 TINYINT 存储、但 ES mapping 为 boolean 的字段（需把 0/1 转成 true/false）
BOOL_COLUMNS: Dict[str, set] = {
    "dws_customer_360": {"is_existing_customer"},
    "dws_interaction_detail": {"is_high_value"},
    "dws_contact_mapping": {"zhique_matched"},
}

# 增量水位表
WATERMARK_TABLE = "es_sync_state"


# ─────────────────────────────────────────────────────────────────────────────
# 客户端与索引定义
# ─────────────────────────────────────────────────────────────────────────────

def get_es_client() -> Elasticsearch:
    """返回共享的 ElasticSearch 客户端。"""
    return Elasticsearch(
        hosts=[{
            "scheme": settings.ES_SCHEME,
            "host": settings.ES_HOST,
            "port": settings.ES_PORT,
        }],
        basic_auth=(settings.ES_USER, settings.ES_PASSWORD),
        verify_certs=settings.ES_VERIFY_CERTS,
        ssl_show_warn=settings.ES_VERIFY_CERTS,
        request_timeout=120,
    )


def _cn_text() -> Dict[str, Any]:
    """中文全文检索字段：ik 分词 + keyword 子字段（用于精确匹配/聚合）。"""
    return {
        "type": "text",
        "analyzer": "cn_analyzer",
        "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
    }


def _kw() -> Dict[str, Any]:
    return {"type": "keyword"}


# 各 DWS 表的索引字段映射
MAPPINGS: Dict[str, Dict[str, Any]] = {
    "dws_customer_360": {
        "customer_name": _cn_text(),
        "industry": _cn_text(),
        "region": _kw(),
        "owner_name": _kw(),
        "attribute": _kw(),
        "campaign_tag": _kw(),
        "purchase_stage": _kw(),
        "forecast_type": _kw(),
        "role_coverage": _kw(),
        "role_detail": {"type": "flattened"},
        "intent_score": {"type": "integer"},
        "intent_level": _kw(),
        "interaction_count_30d": {"type": "integer"},
        "interaction_count_total": {"type": "integer"},
        "last_interaction_time": {"type": "date"},
        "last_interaction_channel": _kw(),
        "top_channels": {"type": "keyword"},
        "active_opp_count": {"type": "integer"},
        "active_opp_amount": {"type": "double"},
        "funnel_opp_count": {"type": "integer"},
        "won_amount": {"type": "double"},
        "highest_stage_opp": {"type": "flattened"},
        "contact_count": {"type": "integer"},
        "mobile_count": {"type": "integer"},
        "product_categories": {"type": "flattened"},
        "is_existing_customer": {"type": "boolean"},
        "source_tables": {"type": "keyword"},
        "data_coverage": {"type": "flattened"},
        "updated_at": {"type": "date"},
    },
    "dws_contact_360": {
        "customer_id": {"type": "long"},
        "contact_name": _cn_text(),
        "mobile": _kw(),
        "email": _kw(),
        "department": _kw(),
        "position": _kw(),
        "purchase_role": _kw(),
        "role_category": _kw(),
        "interaction_count": {"type": "integer"},
        "interaction_count_30d": {"type": "integer"},
        "last_interaction_time": {"type": "date"},
        "top_content_types": {"type": "keyword"},
        "product_interests": {"type": "keyword"},
        "activity_level": _kw(),
        "intent_level": _kw(),
        "lead_stage": _kw(),
        "source_tables": {"type": "keyword"},
        "linkflow_contact_id": {"type": "long"},
        "updated_at": {"type": "date"},
    },
    "dws_interaction_detail": {
        "customer_name": _cn_text(),
        "contact_name": _cn_text(),
        "mobile": _kw(),
        "source_table": _kw(),
        "channel": _kw(),
        "behavior_type": _kw(),
        "content": _cn_text(),
        "event_time": {"type": "date"},
        "is_high_value": {"type": "boolean"},
        "source_id": {"type": "long"},
        "etl_time": {"type": "date"},
    },
    "dws_contact_mapping": {
        "customer_name": _cn_text(),
        "contact_name": _cn_text(),
        "mobile": _kw(),
        "email": _kw(),
        "department": _kw(),
        "position": _kw(),
        "purchase_role": _kw(),
        "role_category": _kw(),
        "source_table": _kw(),
        "linkflow_contact_id": {"type": "long"},
        "zhique_matched": {"type": "boolean"},
        "etl_time": {"type": "date"},
        "updated_at": {"type": "date"},
    },
}


def _index_settings() -> Dict[str, Any]:
    """索引 settings：定义中文分析器（由 ES_ANALYZER 配置决定 ik / standard）。"""
    return {
        "analysis": {
            "analyzer": {
                "cn_analyzer": {"type": settings.ES_ANALYZER},
            }
        },
        "number_of_replicas": 1,
    }


def ensure_index(index_name: str, table: str) -> None:
    """若索引不存在则创建（带 mapping 与中文分析器）。"""
    es = get_es_client()
    if not es.indices.exists(index=index_name):
        es.indices.create(
            index=index_name,
            settings=_index_settings(),
            mappings={"properties": MAPPINGS[table]},
        )
        logger.info("Created ES index %s", index_name)


# ─────────────────────────────────────────────────────────────────────────────
# 行转换
# ─────────────────────────────────────────────────────────────────────────────

def _row_to_doc(table: str, row: Dict[str, Any]) -> Dict[str, Any]:
    """将 MySQL 行（dict）转换为 ES 文档。"""
    doc: Dict[str, Any] = {}
    json_cols = JSON_COLUMNS.get(table, set())
    bool_cols = BOOL_COLUMNS.get(table, set())
    for key, value in row.items():
        if value is None:
            continue
        # TINYINT(0/1) -> boolean（ES mapping 定义为 boolean，否则会 mapper_parsing_exception）
        if key in bool_cols:
            doc[key] = bool(value)
            continue
        if key in json_cols:
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    pass
            # flattened 类型不接受标量字符串：若解析后仍是标量（如 'crm'），
            # 统一包成单元素数组；对象/数组原样保留。
            if value is not None and not isinstance(value, (dict, list)):
                value = [value]
            doc[key] = value
            continue
        if isinstance(value, Decimal):
            doc[key] = float(value)
        elif isinstance(value, (datetime, date)):
            doc[key] = value.isoformat()
        else:
            doc[key] = value
    return doc


# ─────────────────────────────────────────────────────────────────────────────
# 水位（增量基准）
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_watermark_table() -> None:
    from app.services.etl_sync import get_etl_engine
    engine = get_etl_engine()
    with engine.begin() as conn:
        conn.execute(text(
            f"CREATE TABLE IF NOT EXISTS {WATERMARK_TABLE} ("
            f"  id INT PRIMARY KEY DEFAULT 1, "
            f"  last_sync_time DATETIME NOT NULL, "
            f"  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
            f") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        ))
        conn.execute(text(
            f"INSERT IGNORE INTO {WATERMARK_TABLE} (id, last_sync_time) "
            f"VALUES (1, '2000-01-01 00:00:00')"
        ))


def get_watermark() -> datetime:
    from app.services.etl_sync import get_etl_engine
    _ensure_watermark_table()
    engine = get_etl_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text(f"SELECT last_sync_time FROM {WATERMARK_TABLE} WHERE id=1")
        ).fetchone()
    return row[0] if row else datetime(2000, 1, 1)


def set_watermark(ts: datetime) -> None:
    from app.services.etl_sync import get_etl_engine
    _ensure_watermark_table()
    engine = get_etl_engine()
    with engine.begin() as conn:
        conn.execute(
            text(f"UPDATE {WATERMARK_TABLE} SET last_sync_time=:ts WHERE id=1"),
            {"ts": ts},
        )


# ─────────────────────────────────────────────────────────────────────────────
# 批量写入
# ─────────────────────────────────────────────────────────────────────────────

def _switch_alias(es: Elasticsearch, alias: str, new_index: str) -> None:
    """把 alias 原子切换到 new_index，并删除旧索引。"""
    try:
        old = es.indices.get_alias(name=alias)
        remove = [{"remove": {"index": i, "alias": alias}} for i in old]
    except NotFoundError:
        old = {}
        remove = []
    actions = remove + [{"add": {"index": new_index, "alias": alias}}]
    es.indices.update_aliases(actions=actions)
    for idx in old:
        if idx != new_index:
            es.indices.delete(index=idx, ignore=[404])
    logger.info("Alias %s -> %s (removed old: %s)", alias, new_index, list(old))


# ─────────────────────────────────────────────────────────────────────────────
# 全量 / 增量同步
# ─────────────────────────────────────────────────────────────────────────────

def run_es_full_sync() -> Dict[str, Any]:
    """全量重建所有 DWS 索引（alias 轮换，检索不中断）。"""
    from app.services.elasticSearch.es_crud import _bulk
    from app.services.etl_sync import get_etl_engine

    es = get_es_client()
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    results: Dict[str, Any] = {}

    for table, alias in INDEX_MAP.items():
        new_index = f"{alias}_{ts}"
        ensure_index(new_index, table)

        actions: List[Dict[str, Any]] = []
        total = 0
        engine = get_etl_engine()
        with engine.connect() as conn:
            result = conn.execution_options(yield_per=2000).execute(
                text(f"SELECT * FROM {table}")
            )
            for row in result.mappings():
                doc = _row_to_doc(table, row)
                actions.append({
                    "_op_type": "index",
                    "_index": new_index,
                    "_id": str(doc["id"]),
                    "_source": doc,
                })
                if len(actions) >= 2000:
                    total += _bulk(es, actions)
                    actions.clear()
        if actions:
            total += _bulk(es, actions)

        _switch_alias(es, alias, new_index)
        results[table] = total
        logger.info("ES full sync %s: %d docs", table, total)

    set_watermark(datetime.now())
    logger.info("ES full sync completed: %s", results)
    return results


def run_es_incremental_sync() -> Dict[str, Any]:
    """基于水位做增量 upsert，并对小表做孤儿删除检测。"""
    from app.services.elasticSearch.es_crud import _bulk
    from app.services.etl_sync import get_etl_engine

    es = get_es_client()
    last = get_watermark()
    new_ts = datetime.now()
    results: Dict[str, Any] = {}

    for table, alias in INDEX_MAP.items():
        # alias 必须存在（先做过全量）；不存在则跳过
        if not es.indices.exists_alias(name=alias):
            logger.warning("Alias %s not found, skip incremental for %s", alias, table)
            continue

        ts_col = "etl_time" if table == "dws_interaction_detail" else "updated_at"
        actions: List[Dict[str, Any]] = []
        total = 0
        engine = get_etl_engine()
        with engine.connect() as conn:
            result = conn.execution_options(yield_per=2000).execute(
                text(f"SELECT * FROM {table} WHERE {ts_col} > :last"),
                {"last": last},
            )
            for row in result.mappings():
                doc = _row_to_doc(table, row)
                actions.append({
                    "_op_type": "update",
                    "_index": alias,
                    "_id": str(doc["id"]),
                    "doc": doc,
                    "doc_as_upsert": True,
                })
                if len(actions) >= 2000:
                    total += _bulk(es, actions)
                    actions.clear()
        if actions:
            total += _bulk(es, actions)

        pruned = 0
        if table in PRUNE_TABLES:
            pruned = _prune_deleted(es, alias, table)

        results[table] = {"upserted": total, "pruned": pruned}
        logger.info("ES incremental %s: upserted=%d pruned=%d", table, total, pruned)

    set_watermark(new_ts)
    logger.info("ES incremental sync completed: %s", results)
    return results


def _prune_deleted(es: Elasticsearch, alias: str, table: str) -> int:
    """删除 ES 中存在但 MySQL 已不存在的文档（基于 id 集合 diff）。"""
    from app.services.elasticSearch.es_crud import _bulk
    from app.services.etl_sync import get_etl_engine

    engine = get_etl_engine()
    with engine.connect() as conn:
        mysql_ids = {str(r[0]) for r in conn.execute(text(f"SELECT id FROM {table}")).all()}

    es_ids = set()
    for hit in scan(es, index=alias, _source=False, query={"query": {"match_all": {}}}):
        es_ids.add(hit["_id"])

    to_delete = es_ids - mysql_ids
    if not to_delete:
        return 0
    actions = [{"_op_type": "delete", "_index": alias, "_id": i} for i in to_delete]
    _bulk(es, actions)
    logger.info("Pruned %d stale docs from %s", len(to_delete), alias)
    return len(to_delete)


# ─────────────────────────────────────────────────────────────────────────────
# 对外入口
# ─────────────────────────────────────────────────────────────────────────────

def sync_after_etl(sync_type: str) -> Dict[str, Any]:
    """供 ETL 主流程在成功后调用：full -> 全量重建；incremental -> 增量同步。"""
    if sync_type == "full":
        return run_es_full_sync()
    return run_es_incremental_sync()


def get_es_health() -> Dict[str, Any]:
    """返回 ES 连接信息与各索引文档数。"""
    es = get_es_client()
    info = es.info()
    indices: Dict[str, Any] = {}
    for table, alias in INDEX_MAP.items():
        entry: Dict[str, Any] = {"alias": alias}
        try:
            entry["docs"] = es.count(index=alias).get("count", 0)
            entry["exists"] = True
        except Exception:
            entry["exists"] = False
        indices[table] = entry
    return {
        "cluster": info.get("cluster_name"),
        "version": (info.get("version") or {}).get("number"),
        "indices": indices,
    }
