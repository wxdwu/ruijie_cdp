"""
Review Queue API router for company name deduplication review.

仅做 HTTP 编排：参数校验、委托 review_service 处理审核项查询/状态变更，
以及委托 company_dedup 触发去重任务。所有 DDL/UPDATE/JSON 整形逻辑均在 service 层。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.company_dedup.company_merge import list_merges, sync_auto_merged_to_map
from app.services.company_dedup.review_service import (
    ReviewItemNotFound,
    approve_review,
    batch_approve_reviews,
    batch_reject_reviews,
    get_review_items,
    get_review_stats,
    reject_review,
    rollback_review_merge,
    revoke_review,
    batch_revoke_reviews,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/review", tags=["review"])


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Models（请求/响应契约，属于路由层职责）
# ─────────────────────────────────────────────────────────────────────────────

class BatchOperationRequest(BaseModel):
    ids: List[int]


class ReviewStatsResponse(BaseModel):
    pending: int
    auto_merged: int
    merged: int
    rejected: int
    need_review: int
    total: int


def _handle_not_found(item_id: int) -> HTTPException:
    return HTTPException(status_code=404, detail="Review item not found")


@router.get("")
def get_review_items_endpoint(
    db: Session = Depends(get_db),
    review_type: str = Query(None, description="Filter by review_type: company_merge, contact_merge, data_quality"),
    status: str = Query(None, description="Filter by status: pending, auto_merged, merged, rejected, need_review"),
    keyword: str = Query(None, description="模糊匹配候选 A/B 公司名称 candidate_a_name / candidate_b_name"),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Page size (max 100)"),
) -> Dict[str, Any]:
    """Get review items with pagination and filters."""
    return get_review_items(
        db, review_type=review_type, status=status, keyword=keyword, page=page, size=size
    )


@router.get("/stats", response_model=ReviewStatsResponse)
def get_review_stats_endpoint(db: Session = Depends(get_db)) -> ReviewStatsResponse:
    """Get dashboard statistics for review queue."""
    return ReviewStatsResponse(**get_review_stats(db))


@router.post("/sync-auto-merge")
def sync_auto_merge_endpoint() -> Dict[str, Any]:
    """修复端点：把 review_candidate 中 status='auto_merged' 但漏写 company_merge_map 的候选对补同步。

    适用于历史去重运行中「标记了自动合并却没真正合并」的缺口；幂等，可反复调用。
    """
    try:
        persisted = sync_auto_merged_to_map()
        return {
            "success": True,
            "persisted": persisted,
            "message": f"已将 {persisted} 个自动合并候选对同步进 company_merge_map",
        }
    except Exception as e:
        logger.error(f"Sync auto-merge failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")


@router.post("/rebuild-merge-map")
def rebuild_merge_map_endpoint(
    clear: bool = Query(
        True,
        description="truncate company_merge_map then full rebuild from review_candidate (default true, stays consistent with review_candidate); false = incremental upsert only",
    ),
) -> Dict[str, Any]:
    """Rebuild company_merge_map (with alias_id) from review_candidate, for manual trigger.

    review_candidate (auto_merged/merged) is the single source of truth, so the whole
    company_merge_map can be reconstructed from it. Idempotent, safe to call repeatedly.
    Default clears then rebuilds to stay strictly consistent with review_candidate.
    """
    try:
        from app.services.company_dedup.company_merge import (
            rebuild_merge_map_from_review,
        )

        stats = rebuild_merge_map_from_review(clear_existing=clear)
        return {"success": True, **stats}
    except Exception as e:
        logger.error(f"Rebuild merge map failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Rebuild failed: {str(e)}")


@router.post("/{id}/approve")
def approve_merge_endpoint(
    id: int,
    db: Session = Depends(get_db),
    reviewed_by: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """通过审核：写入 company_merge_map，持久化合并（非物理改写 DWS）。"""
    try:
        return approve_review(db, id, reviewed_by=reviewed_by)
    except ReviewItemNotFound:
        raise _handle_not_found(id)


@router.post("/{id}/rollback")
def rollback_merge_endpoint(id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """退回某审核项产生的合并（删除 company_merge_map 中的映射行）。"""
    try:
        deleted = rollback_review_merge(db, id)
        return {
            "success": True,
            "id": id,
            "deleted": deleted,
            "message": "合并已退回" if deleted else "未找到该合并映射",
        }
    except Exception as e:
        logger.error(f"Rollback review item {id} failed: {e}")
        raise HTTPException(status_code=500, detail=f"Rollback failed: {str(e)}")


@router.post("/{id}/reject")
def reject_merge_endpoint(id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Reject a merge request."""
    try:
        return reject_review(db, id)
    except ReviewItemNotFound:
        raise _handle_not_found(id)


@router.post("/batch-approve")
def batch_approve_endpoint(
    request: BatchOperationRequest,
    db: Session = Depends(get_db),
    reviewed_by: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """批量通过审核：写入 company_merge_map，持久化合并。"""
    try:
        return batch_approve_reviews(db, request.ids, reviewed_by=reviewed_by)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/merges")
def list_merges_endpoint(
    db: Session = Depends(get_db),
    canonical_name: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    """列出当前生效的公司合并映射（持久化层审计/管理）。"""
    try:
        return list_merges(db, canonical_name=canonical_name, page=page, size=size)
    except Exception as e:
        logger.error(f"List merges failed: {e}")
        raise HTTPException(status_code=500, detail=f"List merges failed: {str(e)}")


@router.post("/merges/rollback")
def rollback_merge_by_alias_endpoint(
    db: Session = Depends(get_db),
    alias_name: Optional[str] = Query(None),
    review_id: Optional[int] = Query(None),
) -> Dict[str, Any]:
    """按别名或审核项退回合并。"""
    if not alias_name and review_id is None:
        raise HTTPException(status_code=400, detail="alias_name 与 review_id 至少提供一个")
    from app.services.company_dedup.company_merge import rollback_merge_by_alias
    try:
        if alias_name:
            deleted = rollback_merge_by_alias(db, alias_name)
            return {
                "success": True,
                "alias_name": alias_name,
                "deleted": deleted,
                "message": "合并已退回" if deleted else "未找到该别名映射",
            }
        deleted = rollback_review_merge(db, review_id)
        return {
            "success": True,
            "review_id": review_id,
            "deleted": deleted,
            "message": "合并已退回" if deleted else "未找到该合并映射",
        }
    except Exception as e:
        logger.error(f"Rollback merge failed: {e}")
        raise HTTPException(status_code=500, detail=f"Rollback failed: {str(e)}")


@router.post("/batch-reject")
def batch_reject_endpoint(
    request: BatchOperationRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Batch reject multiple merge requests."""
    try:
        return batch_reject_reviews(db, request.ids)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{id}/revoke")
def revoke_review_endpoint(id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """撤销审核：把已审核状态（自动合并 / 手动合并 / 已拒绝）恢复为待人工审核。"""
    try:
        return revoke_review(db, id)
    except ReviewItemNotFound:
        raise _handle_not_found(id)


@router.post("/batch-revoke")
def batch_revoke_endpoint(
    request: BatchOperationRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """批量撤销审核（自动合并 / 手动合并 / 已拒绝 -> 待人工审核）。"""
    try:
        return batch_revoke_reviews(db, request.ids)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/run-dedup")
def run_deduplication(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Trigger the company name deduplication process (background)."""
    from app.services.company_dedup.company_dedup import start_deduplication
    return start_deduplication()


@router.get("/dedup-progress")
def get_dedup_progress() -> Dict[str, Any]:
    """Get the current deduplication progress and results."""
    from app.services.company_dedup.company_dedup import get_dedup_progress
    return get_dedup_progress()
