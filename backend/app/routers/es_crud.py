"""
ElasticSearch 通用增删改查管理 API

端点（均挂在 /api/admin/es 下）：
  POST   /{index}/batch-create    – 批量新增（默认每 5000 条 bulk 一次，batch_size 可配）
  GET    /{index}/{doc_id}        – 按 id 查询
  POST   /{index}/search          – 按 DSL 检索
  PUT    /{index}/{doc_id}        – 按 id 局部更新
  POST   /{index}/batch-update    – 批量更新（doc_as_upsert）
  DELETE /{index}/{doc_id}        – 按 id 删除
  POST   /{index}/batch-delete    – 批量删除（按 id 列表）
  POST   /{index}/delete-by-query – 按查询删除

与 es_sync 路由同属 ES 模块；index 参数可直接传别名（如 cdp_customer_360）。
"""

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.elasticSearch import es_crud

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/es", tags=["elasticsearch-crud"])


class BatchCreateRequest(BaseModel):
    docs: List[Dict[str, Any]] = Field(..., description="文档列表，每个文档建议含 id 字段作为 _id")
    batch_size: int = Field(
        5000, ge=1, le=50000, description="每批写入条数，默认 5000，范围 1~50000"
    )


class BatchUpdateRequest(BaseModel):
    docs: List[Dict[str, Any]] = Field(..., description="更新项列表，每项必须含 id 字段")
    batch_size: int = Field(5000, ge=1, le=50000, description="每批更新条数，默认 5000")


class BatchDeleteRequest(BaseModel):
    ids: List[str] = Field(..., description="待删除文档 id 列表")
    batch_size: int = Field(5000, ge=1, le=50000, description="每批删除条数，默认 5000")


class SearchRequest(BaseModel):
    query: Dict[str, Any] = Field(
        ..., description="ES 查询 DSL（可含 query / sort / aggs / size / from 等）"
    )


class DeleteByQueryRequest(BaseModel):
    query: Dict[str, Any] = Field(..., description="ES 查询 DSL（用于匹配待删除文档）")


@router.post("/{index}/batch-create")
def batch_create(index: str, req: BatchCreateRequest):
    """批量新增文档（批处理，默认 5000 条一批）。"""
    try:
        created = es_crud.es_bulk_create(index, req.docs, req.batch_size)
        return {"status": "ok", "index": index, "created": created}
    except Exception as exc:
        logger.exception("ES batch-create failed")
        raise HTTPException(status_code=500, detail=f"ES batch-create failed: {exc}")


@router.get("/{index}/{doc_id}")
def get_doc(index: str, doc_id: str):
    """按 id 查询单个文档，不存在返回 404。"""
    doc = es_crud.es_get(index, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    return {"index": index, "id": doc_id, "doc": doc}


@router.post("/{index}/search")
def search(index: str, req: SearchRequest):
    """按 DSL 检索文档。"""
    try:
        return es_crud.es_search(index, req.query)
    except Exception as exc:
        logger.exception("ES search failed")
        raise HTTPException(status_code=500, detail=f"ES search failed: {exc}")


@router.put("/{index}/{doc_id}")
def update_doc(index: str, doc_id: str, doc: Dict[str, Any]):
    """按 id 局部更新文档（字段级 merge）。"""
    try:
        es_crud.es_update(index, doc_id, doc)
        return {"status": "ok", "index": index, "id": doc_id, "updated": True}
    except Exception as exc:
        logger.exception("ES update failed")
        raise HTTPException(status_code=500, detail=f"ES update failed: {exc}")


@router.post("/{index}/batch-update")
def batch_update(index: str, req: BatchUpdateRequest):
    """批量更新/upsert（每项必须含 id）。"""
    try:
        updated = es_crud.es_bulk_update(index, req.docs, req.batch_size)
        return {"status": "ok", "index": index, "updated": updated}
    except Exception as exc:
        logger.exception("ES batch-update failed")
        raise HTTPException(status_code=500, detail=f"ES batch-update failed: {exc}")


@router.delete("/{index}/{doc_id}")
def delete_doc(index: str, doc_id: str):
    """按 id 删除文档。"""
    deleted = es_crud.es_delete(index, doc_id)
    return {"status": "ok", "index": index, "id": doc_id, "deleted": deleted}


@router.post("/{index}/batch-delete")
def batch_delete(index: str, req: BatchDeleteRequest):
    """按 id 列表批量删除。"""
    try:
        deleted = es_crud.es_bulk_delete(index, req.ids, req.batch_size)
        return {"status": "ok", "index": index, "deleted": deleted}
    except Exception as exc:
        logger.exception("ES batch-delete failed")
        raise HTTPException(status_code=500, detail=f"ES batch-delete failed: {exc}")


@router.post("/{index}/delete-by-query")
def delete_by_query(index: str, req: DeleteByQueryRequest):
    """按查询 DSL 批量删除匹配的文档。"""
    try:
        deleted = es_crud.es_delete_by_query(index, req.query)
        return {"status": "ok", "index": index, "deleted": deleted}
    except Exception as exc:
        logger.exception("ES delete-by-query failed")
        raise HTTPException(status_code=500, detail=f"ES delete-by-query failed: {exc}")
