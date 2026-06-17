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
# Helper: Ensure review table exists
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_review_table_exists(db: Session) -> None:
    """Create review_candidate table if it doesn't exist."""
    # 检查表是否存在
    check_sql = text("""
        SELECT COUNT(*) as cnt
        FROM information_schema.tables
        WHERE table_schema = DATABASE()
        AND table_name = 'review_candidate'
    """)
    exists = db.execute(check_sql).scalar() or 0

    if not exists:
        # 创建审核队列表，与实际数据库表结构一致
        create_sql = text("""
            CREATE TABLE review_candidate (
                id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                review_type VARCHAR(50) NOT NULL DEFAULT 'company_merge'
                    COMMENT '审核类型: company_merge, contact_merge, data_quality',
                candidate_a_id VARCHAR(128) NOT NULL COMMENT '候选A客户ID',
                candidate_a_name VARCHAR(255) NOT NULL COMMENT '候选公司A名称',
                candidate_b_id VARCHAR(128) NOT NULL COMMENT '候选B客户ID',
                candidate_b_name VARCHAR(255) NOT NULL COMMENT '候选公司B名称',
                match_score DECIMAL(5,2) DEFAULT NULL COMMENT '综合匹配分数',
                rule_score DECIMAL(5,2) DEFAULT NULL COMMENT '规则得分',
                evidence_score DECIMAL(5,2) DEFAULT NULL COMMENT '证据得分',
                llm_score DECIMAL(5,2) DEFAULT NULL COMMENT 'LLM得分',
                status VARCHAR(20) NOT NULL DEFAULT 'pending'
                    COMMENT '状态: pending, auto_merged, rejected, need_review',
                evidence JSON COMMENT '匹配证据详情(含rule_score, evidence_score, llm_score等)',
                reviewed_by VARCHAR(100) DEFAULT NULL COMMENT '审核人',
                reviewed_at DATETIME COMMENT '审核时间',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_review_type (review_type),
                INDEX idx_status (status),
                INDEX idx_match_score (match_score)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            COMMENT='去重审核队列表'
        """)
        db.execute(create_sql)
        db.commit()
        logger.info("Created review_candidate table")


# ─────────────────────────────────────────────────────────────────────────────
# Get review items with pagination
# ─────────────────────────────────────────────────────────────────────────────

def _extract_score_fields(item: Dict[str, Any]) -> Dict[str, Any]:
    """从 evidence JSON 中提取 rule_score, evidence_score, llm_score 等字段，
    同时兼容前端期望的字段名映射。"""
    import json
    # 解析 JSON evidence
    evidence = item.get("evidence")
    if isinstance(evidence, str):
        try:
            evidence = json.loads(evidence)
            item["evidence"] = evidence
        except (json.JSONDecodeError, TypeError):
            evidence = None
            item["evidence"] = None

    # 优先使用数据库列中的分数值，如果为 None 或 0 则从 evidence 提取作为回退
    for score_key in ("rule_score", "evidence_score", "llm_score"):
        db_val = item.get(score_key)
        # 如果数据库列有有效值（非 None 且非 0），直接使用
        if db_val is not None and db_val != 0:
            continue
        # 否则尝试从 evidence 中提取
        if evidence and isinstance(evidence, dict):
            ev_val = evidence.get(score_key)
            if ev_val is not None:
                item[score_key] = ev_val
        # 确保有默认值 0
        if item.get(score_key) is None:
            item[score_key] = 0

    # 前端字段名别名：实际数据库列已经是 candidate_a_name/candidate_b_name
    # 如果 SELECT * 返回了旧的 candidate_a 列名，则自动映射
    if "candidate_a" in item and "candidate_a_name" not in item:
        item["candidate_a_name"] = item["candidate_a"]
    if "candidate_b" in item and "candidate_b_name" not in item:
        item["candidate_b_name"] = item["candidate_b"]

    # ID 字段：如果不存在则设为 None
    if "candidate_a_id" not in item:
        item["candidate_a_id"] = item.get("candidate_a_id") or None
    if "candidate_b_id" not in item:
        item["candidate_b_id"] = item.get("candidate_b_id") or None

    # 审核人字段别名
    if "reviewer" in item and "reviewed_by" not in item:
        item["reviewed_by"] = item["reviewer"]

    # 转换 Decimal 为 float 以便 JSON 序列化
    for key in ("match_score", "rule_score", "evidence_score", "llm_score"):
        val = item.get(key)
        if hasattr(val, '__float__'):
            item[key] = float(val)

    return item


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
    items = [_extract_score_fields(dict(r)) for r in rows]

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
    for status_val, count in rows:
        if status_val in stats:
            stats[status_val] = count
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

    更新状态为 'merged' 并执行实际的公司合并逻辑。
    """
    _ensure_review_table_exists(db)

    # 获取审核项
    item_sql = text("SELECT * FROM review_candidate WHERE id = :id")
    item = db.execute(item_sql, {"id": id}).mappings().fetchone()

    if not item:
        raise HTTPException(status_code=404, detail="Review item not found")

    # 执行实际合并逻辑
    try:
        from app.services.company_dedup import merge_customer_records
        merge_customer_records(
            dict(item), db
        )
    except Exception as e:
        logger.error(f"Merge failed for item {id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"合并失败: {str(e)}"
        )

    # 更新审核状态
    update_sql = text("""
        UPDATE review_candidate
        SET status = 'auto_merged',
            reviewed_by = 'system',
            reviewed_at = NOW()
        WHERE id = :id
    """)
    db.execute(update_sql, {"id": id})
    db.commit()

    logger.info(f"Approved and merged review item {id}")

    return {
        "success": True,
        "id": id,
        "status": "auto_merged",
        "message": "合并通过并已执行",
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

    # 获取审核项
    item_sql = text("SELECT * FROM review_candidate WHERE id = :id")
    item = db.execute(item_sql, {"id": id}).mappings().fetchone()

    if not item:
        raise HTTPException(status_code=404, detail="Review item not found")

    # 更新状态
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
    """Batch approve multiple merge requests with actual merge execution."""
    _ensure_review_table_exists(db)

    if not request.ids:
        raise HTTPException(status_code=400, detail="No IDs provided")

    from app.services.company_dedup import merge_customer_records

    # 逐条执行合并
    approved_count = 0
    errors = []
    for item_id in request.ids:
        try:
            item_sql = text("SELECT * FROM review_candidate WHERE id = :id")
            item = db.execute(item_sql, {"id": item_id}).mappings().fetchone()
            if item:
                merge_customer_records(dict(item), db)

                update_sql = text("""
                    UPDATE review_candidate
                    SET status = 'auto_merged',
                        reviewed_by = 'system',
                        reviewed_at = NOW()
                    WHERE id = :id
                """)
                db.execute(update_sql, {"id": item_id})
                approved_count += 1
        except Exception as e:
            errors.append({"id": item_id, "error": str(e)})
            logger.error(f"Batch approve failed for id {item_id}: {e}")

    db.commit()
    logger.info(f"Batch approved {approved_count} review items")

    return {
        "success": True,
        "approved_count": approved_count,
        "ids": request.ids,
        "errors": errors if errors else None,
        "message": f"Successfully approved {approved_count} items",
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

    # 构建 IN 子句占位符
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
