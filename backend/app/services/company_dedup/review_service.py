"""审核队列服务（去重审核）。

集中审核项查询、状态变更、候选公司详情补充等逻辑，供 review 路由复用，
避免在路由层直接写 DDL/UPDATE SQL 与 JSON 解析（保持 router 只做编排）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.company_dedup.company_dedup import merge_customer_records
from app.services.utils import safe_json_loads, to_json_safe

logger = logging.getLogger(__name__)


class ReviewItemNotFound(Exception):
    """审核项不存在时由 service 抛出，由路由层转换为 404。"""


# ─────────────────────────────────────────────────────────────────────────────
# 表结构与确保存在
# ─────────────────────────────────────────────────────────────────────────────

def ensure_review_table(db: Session) -> None:
    """Create review_candidate table if it doesn't exist."""
    check_sql = text("""
        SELECT COUNT(*) as cnt
        FROM information_schema.tables
        WHERE table_schema = DATABASE()
        AND table_name = 'review_candidate'
    """)
    exists = db.execute(check_sql).scalar() or 0
    if exists:
        return

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
# 数据整形
# ─────────────────────────────────────────────────────────────────────────────

def _extract_score_fields(item: Dict[str, Any]) -> Dict[str, Any]:
    """从 evidence JSON 中提取扩展字段并做兼容映射与类型转换。"""
    evidence = item.get("evidence")
    evidence = safe_json_loads(evidence)
    item["evidence"] = evidence

    # 优先使用数据库列中的分数值，缺失/0 时从 evidence 回退
    for score_key in ("rule_score", "evidence_score", "llm_score"):
        db_val = item.get(score_key)
        if db_val is not None and db_val != 0:
            continue
        if evidence and isinstance(evidence, dict):
            ev_val = evidence.get(score_key)
            if ev_val is not None:
                item[score_key] = ev_val
        if item.get(score_key) is None:
            item[score_key] = 0

    if evidence and isinstance(evidence, dict):
        item["sources_a"] = evidence.get("sources_a", [])
        item["sources_b"] = evidence.get("sources_b", [])
        item["shared_contacts_count"] = evidence.get("shared_contacts_count", 0)
        item["shared_contact_details"] = evidence.get("shared_contact_details", [])
        item["embedding_similarity"] = evidence.get("embedding_similarity")
        item["llm_explanation"] = evidence.get("llm_explanation", "")

    if "candidate_a" in item and "candidate_a_name" not in item:
        item["candidate_a_name"] = item["candidate_a"]
    if "candidate_b" in item and "candidate_b_name" not in item:
        item["candidate_b_name"] = item["candidate_b"]
    if "candidate_a_id" not in item:
        item["candidate_a_id"] = None
    if "candidate_b_id" not in item:
        item["candidate_b_id"] = None
    if "reviewer" in item and "reviewed_by" not in item:
        item["reviewed_by"] = item["reviewer"]

    # 确保所有扩展字段存在默认值
    item.setdefault("sources_a", [])
    item.setdefault("sources_b", [])
    item.setdefault("shared_contacts_count", 0)
    item.setdefault("shared_contact_details", [])
    item.setdefault("embedding_similarity", None)
    item.setdefault("llm_explanation", "")

    # 转换 Decimal 为 float 以便 JSON 序列化
    for key in ("match_score", "rule_score", "evidence_score", "llm_score", "embedding_similarity"):
        val = item.get(key)
        if val is not None:
            item[key] = to_json_safe(val)

    return item


# 补充候选公司在 dws_customer_360 的详情（精确匹配 + 模糊回退）
_COMPANY_DETAIL_COLUMNS = (
    "customer_name", "industry", "region", "owner_name", "contact_count",
    "interaction_count_30d", "interaction_count_total", "last_interaction_time",
    "source_tables", "data_coverage", "intent_level", "purchase_stage",
    "active_opp_count", "is_existing_customer",
)


def _enrich_with_company_details(items: List[Dict[str, Any]], db: Session) -> List[Dict[str, Any]]:
    """为每个审核项补充候选公司的详细字段。"""
    all_names: set = set()
    for item in items:
        a_name = item.get("candidate_a_name", "")
        b_name = item.get("candidate_b_name", "")
        if a_name:
            all_names.add(a_name)
        if b_name:
            all_names.add(b_name)

    if not all_names:
        return items

    details_map: Dict[str, Dict[str, Any]] = {}
    try:
        all_names_list = list(all_names)
        placeholders = ", ".join([f":e{i}" for i in range(len(all_names_list))])
        params_exact = {f"e{i}": name for i, name in enumerate(all_names_list)}
        columns = ", ".join(_COMPANY_DETAIL_COLUMNS)
        detail_sql = text(f"SELECT {columns} FROM dws_customer_360 WHERE customer_name IN ({placeholders})")
        rows = db.execute(detail_sql, params_exact).mappings().all()
        for row in rows:
            detail = dict(row)
            cn = detail["customer_name"]
            for json_field in ("source_tables", "data_coverage"):
                detail[json_field] = safe_json_loads(detail.get(json_field))
            if detail.get("last_interaction_time"):
                detail["last_interaction_time"] = str(detail["last_interaction_time"])
            details_map[cn] = detail

        unmatched = [n for n in all_names_list if n not in details_map]
        if unmatched:
            like_parts = []
            params_like = {}
            for i, name in enumerate(unmatched):
                like_parts.append(f"customer_name LIKE :l{i}")
                params_like[f"l{i}"] = f"%{name}%"
            like_sql = text(
                f"SELECT {columns} FROM dws_customer_360 WHERE {' OR '.join(like_parts)}"
            )
            rows_like = db.execute(like_sql, params_like).mappings().all()
            for row in rows_like:
                detail = dict(row)
                cn = detail["customer_name"]
                if cn in details_map:
                    continue
                for json_field in ("source_tables", "data_coverage"):
                    detail[json_field] = safe_json_loads(detail.get(json_field))
                if detail.get("last_interaction_time"):
                    detail["last_interaction_time"] = str(detail["last_interaction_time"])
                for orig_name in unmatched:
                    if orig_name in cn or cn in orig_name:
                        if orig_name not in details_map:
                            details_map[orig_name] = detail
                        break
                else:
                    details_map[cn] = detail
    except Exception as e:
        logger.warning(f"Failed to enrich company details: {e}")

    for item in items:
        item["candidate_a_detail"] = details_map.get(item.get("candidate_a_name", ""))
        item["candidate_b_detail"] = details_map.get(item.get("candidate_b_name", ""))

    return items


# ─────────────────────────────────────────────────────────────────────────────
# 查询
# ─────────────────────────────────────────────────────────────────────────────

def get_review_items(
    db: Session,
    *,
    review_type: Optional[str] = None,
    status: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = 1,
    size: int = 20,
) -> Dict[str, Any]:
    """分页查询审核项，并补充候选公司详情。

    keyword：模糊匹配候选 A / B 的公司名称（candidate_a_name / candidate_b_name），
    大小写不敏感。输入中的 LIKE 通配符（% / _ / !）会被转义，避免被当作通配符解析。
    """
    ensure_review_table(db)

    where_parts: List[str] = ["1=1"]
    params: Dict[str, Any] = {}
    if review_type:
        where_parts.append("review_type = :review_type")
        params["review_type"] = review_type
    if status:
        where_parts.append("status = :status")
        params["status"] = status
    if keyword:
        # 转义用户输入中的 LIKE 通配符，保证按字面量模糊匹配（避免 %/_ 被当成通配符）
        safe_kw = (
            keyword.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        )
        where_parts.append(
            "(candidate_a_name LIKE :kw ESCAPE '!' "
            "OR candidate_b_name LIKE :kw ESCAPE '!')"
        )
        params["kw"] = f"%{safe_kw}%"
    where_sql = " AND ".join(where_parts)

    total: int = db.execute(
        text(f"SELECT COUNT(*) FROM review_candidate WHERE {where_sql}"),
        params,
    ).scalar() or 0

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
    items = _enrich_with_company_details(items, db)

    return {"total": total, "items": items, "page": page, "size": size}


def get_review_stats(db: Session) -> Dict[str, int]:
    """返回审核队列看板统计。"""
    ensure_review_table(db)
    stats_sql = text("""
        SELECT status, COUNT(*) as count
        FROM review_candidate
        GROUP BY status
    """)
    rows = db.execute(stats_sql).fetchall()
    stats = {"pending": 0, "auto_merged": 0, "rejected": 0, "need_review": 0, "total": 0}
    for status_val, count in rows:
        if status_val in stats:
            stats[status_val] = count
        stats["total"] += count
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# 状态变更（含实际合并逻辑）
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_review_item(db: Session, item_id: int) -> Optional[Dict[str, Any]]:
    item_sql = text("SELECT * FROM review_candidate WHERE id = :id")
    return db.execute(item_sql, {"id": item_id}).mappings().fetchone()


def _set_status(db: Session, item_id: int, status: str) -> None:
    update_sql = text("""
        UPDATE review_candidate
        SET status = :status,
            reviewed_by = 'system',
            reviewed_at = NOW()
        WHERE id = :id
    """)
    db.execute(update_sql, {"id": item_id, "status": status})


def approve_review(db: Session, item_id: int) -> Dict[str, Any]:
    """通过并实际执行客户合并。"""
    item = _fetch_review_item(db, item_id)
    if not item:
        raise ReviewItemNotFound(item_id)
    merge_customer_records(dict(item), db)
    _set_status(db, item_id, "auto_merged")
    db.commit()
    logger.info(f"Approved and merged review item {item_id}")
    return {"success": True, "id": item_id, "status": "auto_merged", "message": "合并通过并已执行"}


def reject_review(db: Session, item_id: int) -> Dict[str, Any]:
    """拒绝合并。"""
    item = _fetch_review_item(db, item_id)
    if not item:
        raise ReviewItemNotFound(item_id)
    _set_status(db, item_id, "rejected")
    db.commit()
    logger.info(f"Rejected merge for review item {item_id}")
    return {"success": True, "id": item_id, "status": "rejected", "message": "Merge rejected successfully"}


def batch_approve_reviews(db: Session, ids: List[int]) -> Dict[str, Any]:
    """批量通过并执行合并。"""
    if not ids:
        raise ValueError("No IDs provided")
    approved_count = 0
    errors = []
    for item_id in ids:
        item = _fetch_review_item(db, item_id)
        if item:
            try:
                merge_customer_records(dict(item), db)
                _set_status(db, item_id, "auto_merged")
                approved_count += 1
            except Exception as e:
                errors.append({"id": item_id, "error": str(e)})
                logger.error(f"Batch approve failed for id {item_id}: {e}")
    db.commit()
    logger.info(f"Batch approved {approved_count} review items")
    return {
        "success": True,
        "approved_count": approved_count,
        "ids": ids,
        "errors": errors if errors else None,
        "message": f"Successfully approved {approved_count} items",
    }


def batch_reject_reviews(db: Session, ids: List[int]) -> Dict[str, Any]:
    """批量拒绝。"""
    if not ids:
        raise ValueError("No IDs provided")
    placeholders = ", ".join([f":id{i}" for i in range(len(ids))])
    params = {f"id{i}": id_val for i, id_val in enumerate(ids)}
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
        "ids": ids,
        "message": f"Successfully rejected {affected} items",
    }
