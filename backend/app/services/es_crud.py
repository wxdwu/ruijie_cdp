"""
ElasticSearch 通用增删改查服务

提供与具体业务无关的 ES 文档 CRUD 能力，供管理后台 / 接口调用：
  - 批量新增（默认每 5000 条 bulk 一次，batch_size 可配）
  - 按 id 查询 / 按 DSL 检索
  - 按 id 局部更新 / 批量更新（doc_as_upsert）
  - 按 id 删除 / 批量删除 / 按查询删除

与 es_sync 同属 ES 模块，复用其 get_es_client()；不在本文件重复维护客户端。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from elasticsearch import Elasticsearch
from elasticsearch.exceptions import NotFoundError
from elasticsearch.helpers import bulk

from app.services.es_sync import get_es_client

logger = logging.getLogger(__name__)

# 批量写入默认每批条数（新增接口可通过 batch_size 覆盖）
DEFAULT_BATCH_SIZE = 5000


def _bulk(es: Elasticsearch, actions: List[Dict[str, Any]]) -> int:
    """执行 bulk，返回成功条数；失败仅记录日志，不抛异常（best-effort）。"""
    if not actions:
        return 0
    success, errors = bulk(es, actions, raise_on_error=False, stats_only=False)
    for err in errors[:10]:
        logger.error("ES bulk error: %s", err)
    if errors:
        logger.warning("ES bulk: %d succeeded, %d errors", success, len(errors))
    return success


def es_bulk_create(
    index: str, docs: List[Dict[str, Any]], batch_size: int = DEFAULT_BATCH_SIZE
) -> int:
    """批量新增文档。每 batch_size 条发起一次 bulk（默认 5000）。

    doc 中的 id / _id 作为 ES 文档 _id；缺省则自动生成 uuid。
    返回成功写入的文档数。
    """
    es = get_es_client()
    batch_size = max(1, int(batch_size))
    total = 0
    actions: List[Dict[str, Any]] = []
    for doc in docs:
        _id = str(doc.get("id") or doc.get("_id") or uuid.uuid4().hex)
        actions.append({"_op_type": "index", "_index": index, "_id": _id, "_source": doc})
        if len(actions) >= batch_size:
            total += _bulk(es, actions)
            actions.clear()
    if actions:
        total += _bulk(es, actions)
    logger.info("ES bulk-create %s: %d docs (batch_size=%d)", index, total, batch_size)
    return total


def es_get(index: str, doc_id: str) -> Optional[Dict[str, Any]]:
    """按 id 查询单个文档，不存在返回 None。"""
    es = get_es_client()
    try:
        resp = es.get(index=index, id=str(doc_id))
        return resp.get("_source")
    except NotFoundError:
        return None


def es_search(index: str, query: Dict[str, Any]) -> Dict[str, Any]:
    """按 ES 查询 DSL 检索（query 可含 query / sort / aggs / size / from 等）。

    返回 {"total": int, "hits": [doc, ...]}。
    """
    es = get_es_client()
    resp = es.search(index=index, body=query)
    total = resp["hits"]["total"]
    total_val = total["value"] if isinstance(total, dict) else total
    hits = [h["_source"] for h in resp["hits"]["hits"]]
    return {"total": total_val, "hits": hits}


def es_update(index: str, doc_id: str, doc: Dict[str, Any]) -> bool:
    """按 id 局部更新文档（字段级 merge）。"""
    es = get_es_client()
    es.update(index=index, id=str(doc_id), doc=doc)
    return True


def es_bulk_update(
    index: str, items: List[Dict[str, Any]], batch_size: int = DEFAULT_BATCH_SIZE
) -> int:
    """批量更新/upsert。每个 item 必须含 id 字段（作为 _id），其余为待更新字段。

    返回成功更新的文档数。
    """
    es = get_es_client()
    batch_size = max(1, int(batch_size))
    total = 0
    actions: List[Dict[str, Any]] = []
    for item in items:
        item = dict(item)
        _id = str(item.pop("id", None) or item.pop("_id", None) or uuid.uuid4().hex)
        actions.append({
            "_op_type": "update",
            "_index": index,
            "_id": _id,
            "doc": item,
            "doc_as_upsert": True,
        })
        if len(actions) >= batch_size:
            total += _bulk(es, actions)
            actions.clear()
    if actions:
        total += _bulk(es, actions)
    logger.info("ES bulk-update %s: %d docs (batch_size=%d)", index, total, batch_size)
    return total


def es_delete(index: str, doc_id: str) -> bool:
    """按 id 删除文档，不存在返回 False。"""
    es = get_es_client()
    try:
        es.delete(index=index, id=str(doc_id))
        return True
    except NotFoundError:
        return False


def es_bulk_delete(
    index: str, ids: List[str], batch_size: int = DEFAULT_BATCH_SIZE
) -> int:
    """按 id 列表批量删除。返回成功删除的文档数。"""
    es = get_es_client()
    batch_size = max(1, int(batch_size))
    total = 0
    actions: List[Dict[str, Any]] = []
    for _id in ids:
        actions.append({"_op_type": "delete", "_index": index, "_id": str(_id)})
        if len(actions) >= batch_size:
            total += _bulk(es, actions)
            actions.clear()
    if actions:
        total += _bulk(es, actions)
    logger.info("ES bulk-delete %s: %d docs (batch_size=%d)", index, total, batch_size)
    return total


def es_delete_by_query(index: str, query: Dict[str, Any]) -> int:
    """按查询 DSL 删除匹配的文档。返回删除条数。"""
    es = get_es_client()
    resp = es.delete_by_query(index=index, body=query, conflicts="proceed")
    return resp.get("deleted", 0)
