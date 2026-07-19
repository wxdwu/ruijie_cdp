"""
Review Queue API router for company name deduplication review.

仅做 HTTP 编排：参数校验、委托 review_service 处理审核项查询/状态变更，
以及委托 company_dedup 触发去重任务。所有 DDL/UPDATE/JSON 整形逻辑均在 service 层。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.company_dedup.review_service import (
    ReviewItemNotFound,
    approve_review,
    batch_approve_reviews,
    batch_reject_reviews,
    get_review_items,
    get_review_stats,
    reject_review,
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
    rejected: int
    need_review: int
    total: int


def _handle_not_found(item_id: int) -> HTTPException:
    return HTTPException(status_code=404, detail="Review item not found")


@router.get("")
def get_review_items_endpoint(
    db: Session = Depends(get_db),
    review_type: str = Query(None, description="Filter by review_type: company_merge, contact_merge, data_quality"),
    status: str = Query(None, description="Filter by status: pending, auto_merged, rejected, need_review"),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Page size (max 100)"),
) -> Dict[str, Any]:
    """Get review items with pagination and filters."""
    return get_review_items(
        db, review_type=review_type, status=status, page=page, size=size
    )


@router.get("/stats", response_model=ReviewStatsResponse)
def get_review_stats_endpoint(db: Session = Depends(get_db)) -> ReviewStatsResponse:
    """Get dashboard statistics for review queue."""
    return ReviewStatsResponse(**get_review_stats(db))


@router.post("/{id}/approve")
def approve_merge_endpoint(id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Approve a merge request and execute the actual company merge."""
    try:
        return approve_review(db, id)
    except ReviewItemNotFound:
        raise _handle_not_found(id)


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
) -> Dict[str, Any]:
    """Batch approve multiple merge requests with actual merge execution."""
    try:
        return batch_approve_reviews(db, request.ids)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
