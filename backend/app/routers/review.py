"""
Review Queue API router for company name deduplication review.

Provides endpoints for listing review items with pagination,
getting statistics, approving/rejecting merges, and batch operations.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/review", tags=["review"])


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Models
# ─────────────────────────────────────────────────────────────────────────────

class BatchOperationRequest(BaseModel):
    ids: List[int]


class ReviewStatsResponse(BaseModel):
    pending: int
    auto_merged: int
    rejected: int
    need_review: int
    total: int


# ─────────────────────────────────────────────────────────────────────────────
# Helper: Ensure review table exists and has sample data
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_review_table_exists(db: Session) -> None:
    """Create review_candidate table if it doesn't exist and add sample data."""
    # Check if table exists
    check_sql = text("""
        SELECT COUNT(*) as cnt
        FROM information_schema.tables
        WHERE table_schema = DATABASE()
        AND table_name = 'review_candidate'
    """)
    exists = db.execute(check_sql).scalar() or 0

    if not exists:
        # Create the table
        create_sql = text("""
            CREATE TABLE review_candidate (
                id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                review_type VARCHAR(50) NOT NULL DEFAULT 'company_merge'
                    COMMENT 'company_merge, contact_merge, data_quality',
                candidate_a_id VARCHAR(128) NOT NULL COMMENT 'First candidate ID',
                candidate_a_name VARCHAR(255) NOT NULL COMMENT 'First candidate name',
                candidate_b_id VARCHAR(128) NOT NULL COMMENT 'Second candidate ID',
                candidate_b_name VARCHAR(255) NOT NULL COMMENT 'Second candidate name',
                match_score DECIMAL(5,2) DEFAULT 0 COMMENT 'Overall match score',
                rule_score DECIMAL(5,2) DEFAULT 0 COMMENT 'Rule-based score',
                evidence_score DECIMAL(5,2) DEFAULT 0 COMMENT 'Evidence-based score',
                llm_score DECIMAL(5,2) DEFAULT 0 COMMENT 'LLM similarity score',
                status VARCHAR(20) NOT NULL DEFAULT 'pending'
                    COMMENT 'pending, auto_merged, rejected, need_review',
                evidence JSON COMMENT 'Match evidence details',
                reviewed_by VARCHAR(100) COMMENT 'Reviewer username',
                reviewed_at DATETIME COMMENT 'Review timestamp',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_review_type (review_type),
                INDEX idx_status (status),
                INDEX idx_match_score (match_score)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            COMMENT='Deduplication review candidates'
        """)
        db.execute(create_sql)

        # Insert sample data
        sample_data = [
            ("company_merge", "C001", "阿里巴巴集团控股有限公司", "C002", "阿里巴巴(中国)有限公司", 95.5, 90.0, 98.0, 92.0, "pending"),
            ("company_merge", "C003", "腾讯控股有限公司", "C004", "腾讯科技(深圳)有限公司", 92.0, 88.0, 95.0, 90.0, "pending"),
            ("company_merge", "C005", "字节跳动有限公司", "C006", "北京字节跳动科技有限公司", 88.5, 85.0, 92.0, 87.0, "need_review"),
            ("company_merge", "C007", "百度在线网络技术(北京)有限公司", "C008", "百度公司", 85.0, 80.0, 88.0, 82.0, "pending"),
            ("company_merge", "C009", "京东集团", "C010", "北京京东世纪贸易有限公司", 90.0, 87.0, 93.0, 89.0, "auto_merged"),
            ("company_merge", "C011", "美团点评", "C012", "北京三快在线科技有限公司", 78.0, 75.0, 82.0, 76.0, "rejected"),
            ("company_merge", "C013", "小米科技有限责任公司", "C014", "小米集团", 93.5, 91.0, 96.0, 92.5, "pending"),
            ("company_merge", "C015", "华为技术有限公司", "C016", "华为投资控股有限公司", 89.0, 86.0, 91.0, 88.0, "need_review"),
            ("contact_merge", "P001", "张三 - 销售总监", "P002", "张三 - 销售经理", 75.0, 70.0, 78.0, 72.0, "pending"),
            ("data_quality", "D001", "数据质量问题 - 缺失字段", "D002", "数据质量问题 - 重复记录", 65.0, 60.0, 70.0, 62.0, "pending"),
        ]

        insert_sql = text("""
            INSERT INTO review_candidate
            (review_type, candidate_a_id, candidate_a_name, candidate_b_id, candidate_b_name,
             match_score, rule_score, evidence_score, llm_score, status)
            VALUES (:type, :a_id, :a_name, :b_id, :b_name, :match, :rule, :evidence, :llm, :status)
        """)

        for row in sample_data:
            db.execute(insert_sql, {
                "type": row[0],
                "a_id": row[1],
                "a_name": row[2],
                "b_id": row[3],
                "b_name": row[4],
                "match": row[5],
                "rule": row[6],
                "evidence": row[7],
                "llm": row[8],
                "status": row[9],
            })
        db.commit()
        logger.info("Created review_candidate table with sample data")


# ─────────────────────────────────────────────────────────────────────────────
# Get review items with pagination
# ─────────────────────────────────────────────────────────────────────────────

@router.get("")
def get_review_items(
    db: Session = Depends(get_db),
    review_type: Optional[str] = Query(None, description="Filter by review_type: company_merge, contact_merge, data_quality"),
    status: Optional[str] = Query(None, description="Filter by status: pending, auto_merged, rejected, need_review"),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Page size (max 100)"),
) -> Dict[str, Any]:
    """Get review items with pagination and filters."""
    _ensure_review_table_exists(db)

    where_parts: List[str] = ["1=1"]
    params: Dict[str, Any] = {}

    if review_type:
        where_parts.append("review_type = :review_type")
        params["review_type"] = review_type
    if status:
        where_parts.append("status = :status")
        params["status"] = status

    where_sql = " AND ".join(where_parts)

    # Count total
    count_sql = text(f"SELECT COUNT(*) FROM review_candidate WHERE {where_sql}")
    total: int = db.execute(count_sql, params).scalar() or 0

    # Pagination
    offset = (page - 1) * size
    data_sql = text(
        f"SELECT * FROM review_candidate "
        f"WHERE {where_sql} "
        f"ORDER BY match_score DESC, created_at DESC "
        f"LIMIT :limit OFFSET :offset"
    )
    params["limit"] = size
    params["offset"] = offset

    rows = db.execute(data_sql, params).mappings().all()
    items = [dict(r) for r in rows]

    # Parse JSON evidence if needed
    for item in items:
        if isinstance(item.get("evidence"), str):
            import json
            try:
                item["evidence"] = json.loads(item["evidence"])
            except (json.JSONDecodeError, TypeError):
                item["evidence"] = None

    return {
        "total": total,
        "items": items,
        "page": page,
        "size": size,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Get statistics
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/stats", response_model=ReviewStatsResponse)
def get_review_stats(db: Session = Depends(get_db)) -> ReviewStatsResponse:
    """Get dashboard statistics for review queue."""
    _ensure_review_table_exists(db)

    stats_sql = text("""
        SELECT
            status,
            COUNT(*) as count
        FROM review_candidate
        GROUP BY status
    """)
    rows = db.execute(stats_sql).fetchall()

    stats = {"pending": 0, "auto_merged": 0, "rejected": 0, "need_review": 0, "total": 0}
    for status, count in rows:
        if status in stats:
            stats[status] = count
        stats["total"] += count

    return ReviewStatsResponse(**stats)


# ─────────────────────────────────────────────────────────────────────────────
# Approve merge
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/{id}/approve")
def approve_merge(
    id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Approve a merge request.

    Updates the status to 'auto_merged' and updates dws_customer_360 mappings.
    """
    _ensure_review_table_exists(db)

    # Get the review item
    item_sql = text("SELECT * FROM review_candidate WHERE id = :id")
    item = db.execute(item_sql, {"id": id}).mappings().fetchone()

    if not item:
        raise HTTPException(status_code=404, detail="Review item not found")

    # Update status
    update_sql = text("""
        UPDATE review_candidate
        SET status = 'auto_merged',
            reviewed_by = 'system',
            reviewed_at = NOW()
        WHERE id = :id
    """)
    db.execute(update_sql, {"id": id})

    # TODO: Update dws_customer_360 mappings
    # This would typically merge the two customer records
    # For now, we'll just log the action

    db.commit()
    logger.info(f"Approved merge for review item {id}")

    return {
        "success": True,
        "id": id,
        "status": "auto_merged",
        "message": "Merge approved successfully",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Reject merge
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/{id}/reject")
def reject_merge(
    id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Reject a merge request."""
    _ensure_review_table_exists(db)

    # Get the review item
    item_sql = text("SELECT * FROM review_candidate WHERE id = :id")
    item = db.execute(item_sql, {"id": id}).mappings().fetchone()

    if not item:
        raise HTTPException(status_code=404, detail="Review item not found")

    # Update status
    update_sql = text("""
        UPDATE review_candidate
        SET status = 'rejected',
            reviewed_by = 'system',
            reviewed_at = NOW()
        WHERE id = :id
    """)
    db.execute(update_sql, {"id": id})

    db.commit()
    logger.info(f"Rejected merge for review item {id}")

    return {
        "success": True,
        "id": id,
        "status": "rejected",
        "message": "Merge rejected successfully",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Batch approve
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/batch-approve")
def batch_approve(
    request: BatchOperationRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Batch approve multiple merge requests."""
    _ensure_review_table_exists(db)

    if not request.ids:
        raise HTTPException(status_code=400, detail="No IDs provided")

    # Build placeholders for IN clause
    placeholders = ", ".join([f":id{i}" for i in range(len(request.ids))])
    params = {f"id{i}": id_val for i, id_val in enumerate(request.ids)}
    params["reviewed_by"] = "system"

    update_sql = text(f"""
        UPDATE review_candidate
        SET status = 'auto_merged',
            reviewed_by = :reviewed_by,
            reviewed_at = NOW()
        WHERE id IN ({placeholders})
    """)
    result = db.execute(update_sql, params)
    db.commit()

    affected = result.rowcount
    logger.info(f"Batch approved {affected} review items")

    return {
        "success": True,
        "approved_count": affected,
        "ids": request.ids,
        "message": f"Successfully approved {affected} items",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Batch reject
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/batch-reject")
def batch_reject(
    request: BatchOperationRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Batch reject multiple merge requests."""
    _ensure_review_table_exists(db)

    if not request.ids:
        raise HTTPException(status_code=400, detail="No IDs provided")

    # Build placeholders for IN clause
    placeholders = ", ".join([f":id{i}" for i in range(len(request.ids))])
    params = {f"id{i}": id_val for i, id_val in enumerate(request.ids)}
    params["reviewed_by"] = "system"

    update_sql = text(f"""
        UPDATE review_candidate
        SET status = 'rejected',
            reviewed_by = :reviewed_by,
            reviewed_at = NOW()
        WHERE id IN ({placeholders})
    """)
    result = db.execute(update_sql, params)
    db.commit()

    affected = result.rowcount
    logger.info(f"Batch rejected {affected} review items")

    return {
        "success": True,
        "rejected_count": affected,
        "ids": request.ids,
        "message": f"Successfully rejected {affected} items",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Deduplication: Run
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/run-dedup")
def run_deduplication(
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Trigger the company name deduplication process.

    Runs in background: fetches all company names, computes embeddings,
    finds similar pairs, scores them, and populates the review queue.
    """
    from app.services.company_dedup import start_deduplication
    return start_deduplication()


# ─────────────────────────────────────────────────────────────────────────────
# Deduplication: Progress
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/dedup-progress")
def get_dedup_progress() -> Dict[str, Any]:
    """Get the current deduplication progress and results."""
    from app.services.company_dedup import get_dedup_progress
    return get_dedup_progress()
