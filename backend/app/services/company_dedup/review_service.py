"""审核队列服务（去重审核）。

集中审核项查询、状态变更、候选公司详情补充等逻辑，供 review 路由复用，
避免在路由层直接写 DDL/UPDATE SQL 与 JSON 解析（保持 router 只做编排）。
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.company_dedup.company_merge import (
    _resolve_name,
    record_merge,
    rebuild_merge_map_from_review,
    rollback_merge_by_review_id,
)
from app.services.company_dedup.company_dedup import (
    batch_calculate_evidence_scores,
)
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
                COMMENT '状态: pending, auto_merged(系统自动合并), merged(人工审核合并), rejected, need_review',
            evidence JSON COMMENT '匹配证据详情(含rule_score, evidence_score, llm_score等)',
            reviewed_by VARCHAR(100) DEFAULT NULL COMMENT '审核人',
            reviewed_at DATETIME COMMENT '审核时间',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_review_type (review_type),
            INDEX idx_status_score (status, match_score DESC, created_at DESC)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        COMMENT='去重审核队列表'
    """)
    db.execute(create_sql)
    db.commit()
    logger.info("Created review_candidate table")
    # 复合索引：覆盖「按 status 过滤 + 按 match_score/created_at 排序 + LIMIT」的常用查询，
    # 避免对全表做 filesort。表已存在时 CREATE INDEX 会报重复索引，捕获后忽略即可（幂等）。
    try:
        db.execute(text(
            "CREATE INDEX idx_status_score ON review_candidate "
            "(status, match_score DESC, created_at DESC)"
        ))
        db.commit()
    except Exception:
        db.rollback()


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


# 补充候选公司在 dws_customer_360 的详情（精确匹配 + 合并映射别名解析，绝不跨公司借用画像）
_COMPANY_DETAIL_COLUMNS = (
    "id", "customer_name", "industry", "region", "owner_name", "contact_count",
    "interaction_count_30d", "interaction_count_total", "last_interaction_time",
    "source_tables", "data_coverage", "intent_level", "purchase_stage",
    "active_opp_count", "is_existing_customer",
)


def _as_dt(value: Any) -> Optional[datetime]:
    """把 event_time（datetime / date / 字符串）归一为 datetime，便于近 30 天判定。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None


def _in_clause(prefix: str, values: List[Any]) -> "tuple[str, Dict[str, Any]]":
    """构造 IN (...) 占位符与参数（兼容 MySQL 与 SQLite，避免依赖驱动展开元组）。"""
    placeholders = ", ".join([f":{prefix}{i}" for i in range(len(values))])
    params = {f"{prefix}{i}": v for i, v in enumerate(values)}
    return f"({placeholders})", params


def _filter_source_tags(
    sources: Any,
    presence: Optional[Dict[str, bool]],
) -> Any:
    """只保留公司真实存在数据的来源表标签。

    - dws_customer_360：公司存在于 360（presence 非空即存在）时保留；
    - dws_contact_mapping：仅当公司在 dws_contact_mapping 确有记录时保留；
    - dws_interaction_detail：仅当公司确有互动明细时保留；
    - 无法确认（presence 为 None）时原样返回，避免误删既有来源信息。
    """
    if not sources or presence is None:
        return sources
    has_contact_mapping = presence.get("contact_mapping", False)
    has_interaction_detail = presence.get("interaction_detail", False)
    kept = []
    for src in sources:
        if not isinstance(src, dict):
            kept.append(src)
            continue
        table = src.get("table")
        if table == "dws_contact_mapping" and not has_contact_mapping:
            continue
        if table == "dws_interaction_detail" and not has_interaction_detail:
            continue
        kept.append(src)
    return kept


def _enrich_with_company_details(items: List[Dict[str, Any]], db: Session) -> List[Dict[str, Any]]:
    """为每个审核项补充候选公司的详细字段。

    外层审核列表 = 原公司名的「原始数据」，不做跨合并簇聚合：
    - 联系人数量从 dws_contact_360（CRM + 营销 + linkflow + 天润 + 智企明细等全部
      来源，与详情页口径一致）按原公司名自身计数；注意 dws_customer_360.contact_count
      仅来自 ods_crm_contact_day（CRM 单一来源），在公司有非 CRM 联系人时会偏小，
      因此此处覆盖它以免内外不一致。
    - 近 30 天互动 / 总互动 / 最近互动时间直接采用 dws_customer_360 中该原公司名
      自身的值（这些数据本身即来自 dws_interaction_detail 全来源，与详情页一致）。
      合并后的汇总数据仅出现在详情页，由 customer_service.resolve_customer 折叠，
      不在此处借用其它公司画像；
    - 仅当候选名不在 360 时，用合并映射把别名解析到当前仍存在的标准名再取档
      （仍取该标准名自身的原始数据），杜绝跨公司错配；
    - 来源表标签仅保留原公司名真实存在数据的表（不跨合并簇）。
    """
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
        # 第一遍：从 dws_customer_360 取候选公司基础画像（精确 + 合并映射别名解析）
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
            for orig_name in unmatched:
                # 仅用合并映射把候选别名名解析到当前 360 中仍存在的标准名，
                # 再精确取档；绝不借用其它公司画像（杜绝跨公司错配）。
                canonical = None
                try:
                    canonical = _resolve_name(db, orig_name)
                except Exception:
                    # 合并映射表缺失/异常时退化为不解析，保持「缺省即空」行为。
                    canonical = None
                if not canonical or canonical == orig_name:
                    continue
                row = db.execute(
                    text(f"SELECT {columns} FROM dws_customer_360 "
                         f"WHERE customer_name = :n"),
                    {"n": canonical},
                ).mappings().fetchone()
                if not row:
                    continue
                detail = dict(row)
                for json_field in ("source_tables", "data_coverage"):
                    detail[json_field] = safe_json_loads(detail.get(json_field))
                if detail.get("last_interaction_time"):
                    detail["last_interaction_time"] = str(detail["last_interaction_time"])
                details_map[orig_name] = detail
    except Exception as e:
        logger.warning(f"Failed to enrich company details: {e}")

    # 来源表真实存在性：仅判断各原公司名自身是否在 dws_contact_mapping /
    # dws_interaction_detail 有记录，用于过滤「数据表」标签（不跨合并簇）。
    cm_names: set = set()
    it_names: set = set()
    try:
        all_names_list = list(all_names)
        if all_names_list:
            names_clause, names_params = _in_clause("mn", all_names_list)
            for r in db.execute(
                text(
                    "SELECT customer_name FROM dws_contact_mapping "
                    f"WHERE customer_name IN {names_clause} GROUP BY customer_name"
                ),
                names_params,
            ).mappings().all():
                cm_names.add(r["customer_name"])
            for r in db.execute(
                text(
                    "SELECT customer_name FROM dws_interaction_detail "
                    f"WHERE customer_name IN {names_clause} GROUP BY customer_name"
                ),
                names_params,
            ).mappings().all():
                it_names.add(r["customer_name"])
    except Exception as e:
        logger.warning(f"Failed to compute presence map: {e}")

    # 联系人真实数量：dws_customer_360.contact_count 仅来自 ods_crm_contact_day
    # （CRM 单一来源），而详情页从 dws_contact_360（CRM + 营销 + linkflow + 天润 +
    # 智企明细等全部来源）计数，二者在公司有非 CRM 联系人时会不一致。为保持「外层=
    # 原始数据」与详情页口径一致，这里改用 dws_contact_360 按原公司名自身计数（不跨
    # 合并簇），覆盖 dws_customer_360 中偏小的 CRM-only 值。
    contact_counts: Dict[str, int] = {}
    try:
        real_names = list({d.get("customer_name") for d in details_map.values() if d})
        if real_names:
            cc_clause, cc_params = _in_clause("ccn", real_names)
            for r in db.execute(
                text(
                    "SELECT c360.customer_name, COUNT(*) AS cnt "
                    "FROM dws_contact_360 cc "
                    "JOIN dws_customer_360 c360 ON c360.id = cc.customer_id "
                    f"WHERE c360.customer_name IN {cc_clause} "
                    "GROUP BY c360.customer_name"
                ),
                cc_params,
            ).mappings().all():
                contact_counts[r["customer_name"]] = int(r["cnt"])
    except Exception as e:
        logger.warning(f"Failed to compute contact counts: {e}")

    # 构造来源表存在性映射；联系人 / 互动计数取 dws_contact_360 / dws_interaction_detail
    # 中该原公司名自身的值（不跨簇聚合，与「外层=原始数据」的设计一致）。
    presence_map: Dict[str, Dict[str, bool]] = {}
    for name, detail in details_map.items():
        if not detail:
            presence_map[name] = {"contact_mapping": False, "interaction_detail": False}
            continue
        # 用 dws_contact_360 全来源真实联系人数覆盖 dws_customer_360 的 CRM-only 值
        real_name = detail.get("customer_name") or name
        if real_name in contact_counts:
            detail["contact_count"] = contact_counts[real_name]
        has_cm = name in cm_names or (detail.get("contact_count") or 0) > 0
        has_it = name in it_names or (detail.get("interaction_count_total") or 0) > 0
        presence_map[name] = {
            "contact_mapping": has_cm,
            "interaction_detail": has_it,
        }

    # 回填到每个审核项，并按真实存在性过滤来源表标签
    for item in items:
        a_name = item.get("candidate_a_name", "")
        b_name = item.get("candidate_b_name", "")
        item["candidate_a_detail"] = details_map.get(a_name)
        item["candidate_b_detail"] = details_map.get(b_name)
        item["sources_a"] = _filter_source_tags(item.get("sources_a"), presence_map.get(a_name))
        item["sources_b"] = _filter_source_tags(item.get("sources_b"), presence_map.get(b_name))

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

    # 实时重算共享联系人，覆盖 review_candidate 表中可能过期的脏缓存。
    # 旧逻辑/历史累积写入的 evidence.shared_contacts_count 可能与真实 dws_contact_mapping
    # 不符（如数量虚高、详情与计数不一致），此处统一按「(姓名,电话)相同」规则重新计算，
    # 保证前端展示的共享联系人数量始终准确，且不会含空姓名/空电话的脏数据。
    if items:
        pairs = [
            (it.get("candidate_a_name", ""), it.get("candidate_b_name", ""))
            for it in items
        ]
        try:
            fresh_scores = batch_calculate_evidence_scores(pairs, db=db)
            for it in items:
                key = (it.get("candidate_a_name", ""), it.get("candidate_b_name", ""))
                if key in fresh_scores:
                    _, shared_count, shared_details = fresh_scores[key]
                    it["shared_contacts_count"] = shared_count
                    it["shared_contact_details"] = shared_details
        except Exception as e:  # 重算失败不应阻断列表展示，降级沿用缓存值
            logger.warning("实时重算共享联系人失败，降级使用缓存值: %s", e)

    # ── 校正候选 id 错位 ──
    # dws_customer_360 每日被 ETL 重建、AUTO_INCREMENT 主键重排，去重时写入的
    # candidate_a_id/b_id（基于当时 360 名->id 映射）会随重建而指向不同的公司，
    # 造成「公司名 ↔ id」错位。此处用当前 360 按候选公司名重新定位真实 id，
    # 覆盖陈旧的存储值，保证前端展示的 id 与画像、跳转一致。合并逻辑只用公司名，
    # 不受此覆盖影响。
    for item in items:
        for side in ("a", "b"):
            detail = item.get(f"candidate_{side}_detail")
            if detail and detail.get("id") is not None:
                item[f"candidate_{side}_id"] = detail["id"]
        # 同步校正「数据表」标签里 dws_customer_360 的 record_id，否则仍显示旧 id
        for side, sources_key in (("a", "sources_a"), ("b", "sources_b")):
            cur_id = item.get(f"candidate_{side}_id")
            for src in (item.get(sources_key) or []):
                if (
                    isinstance(src, dict)
                    and src.get("table") == "dws_customer_360"
                    and cur_id is not None
                ):
                    src["record_id"] = cur_id

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
    stats = {
        "pending": 0,
        "auto_merged": 0,
        "merged": 0,
        "rejected": 0,
        "need_review": 0,
        "total": 0,
    }
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


def approve_review(db: Session, item_id: int, reviewed_by: Optional[str] = None) -> Dict[str, Any]:
    """通过审核：把候选对记录进 company_merge_map（持久化合并，非物理改写 DWS）。"""
    item = _fetch_review_item(db, item_id)
    if not item:
        raise ReviewItemNotFound(item_id)
    _merge_review_item(db, item, reviewed_by=reviewed_by)
    # 手动审核合并用独立的 status='merged'，与系统自动合并 status='auto_merged'
    # 区分，便于按合并方式统计/追溯（两者都已写入 company_merge_map 真正合并）。
    _set_status(db, item_id, "merged")
    db.commit()
    logger.info(f"Approved and merged review item {item_id}")
    return {"success": True, "id": item_id, "status": "merged", "message": "合并通过并已持久化"}


def reject_review(db: Session, item_id: int) -> Dict[str, Any]:
    """拒绝合并。"""
    item = _fetch_review_item(db, item_id)
    if not item:
        raise ReviewItemNotFound(item_id)
    _set_status(db, item_id, "rejected")
    db.commit()
    logger.info(f"Rejected merge for review item {item_id}")
    return {"success": True, "id": item_id, "status": "rejected", "message": "Merge rejected successfully"}


def _merge_review_item(
    db: Session, item: Dict[str, Any], reviewed_by: Optional[str] = None
) -> Dict[str, Any]:
    """把一个审核候选对记录进 company_merge_map。

    尊重分支机构合并：若证据里指定了 branch_canonical，则以它为标准名。
    """
    force_canonical = None
    evidence = item.get("evidence")
    if evidence:
        data = safe_json_loads(evidence)
        if isinstance(data, dict):
            force_canonical = data.get("branch_canonical")
    return record_merge(
        db,
        item["candidate_a_name"],
        item["candidate_b_name"],
        review_id=item.get("id"),
        merged_by=reviewed_by or item.get("reviewed_by") or "system",
        merge_source="manual",
        force_canonical=force_canonical,
    )


def rollback_review_merge(db: Session, item_id: int) -> int:
    """退回某个审核项产生的合并（删除其在 company_merge_map 中的映射行）。

    返回删除的映射行数。退回后别名立即在查询层重新独立显示。
    """
    return rollback_merge_by_review_id(db, item_id)


def batch_approve_reviews(
    db: Session, ids: List[int], reviewed_by: Optional[str] = None
) -> Dict[str, Any]:
    """批量通过并持久化合并。"""
    if not ids:
        raise ValueError("No IDs provided")
    approved_count = 0
    errors = []
    for item_id in ids:
        item = _fetch_review_item(db, item_id)
        if item:
            try:
                _merge_review_item(db, item, reviewed_by=reviewed_by)
                # 手动批量审核合并同样用 status='merged' 区分自动合并
                _set_status(db, item_id, "merged")
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


# 可撤销回「待人工审核」的已审核状态
_REVOCABLE_STATUSES = ("auto_merged", "merged", "rejected")


def revoke_review(db: Session, item_id: int) -> Dict[str, Any]:
    """撤销审核：把已审核状态（自动合并 / 手动合并 / 已拒绝）恢复为待人工审核。

    - 自动合并 / 手动合并：先将该项状态改回 need_review 并提交，使 review_candidate
      立即不再把它视为已合并；再以 review_candidate 为唯一真源重建 company_merge_map
      （清表 + 回填）。这样即便该合并曾被后续传递合并改写过 review_id，也能被彻底
      解除（单纯按 review_id 删除在传递合并场景下会漏删，导致前端仍聚合），无需重跑
      ETL。
    - 已拒绝：未写入合并映射，仅将状态改回 need_review，不动 company_merge_map。
    """
    item = _fetch_review_item(db, item_id)
    if not item:
        raise ReviewItemNotFound(item_id)
    if item["status"] not in _REVOCABLE_STATUSES:
        return {
            "success": False,
            "id": item_id,
            "status": item["status"],
            "message": "该审核项不是已审核状态，无法撤销",
        }
    was_merged = item["status"] in ("auto_merged", "merged")
    # 先把状态改回待人工审核并提交，使 review_candidate 立即不再包含该合并项
    _set_status(db, item_id, "need_review")
    db.commit()
    if was_merged:
        # 以 review_candidate 为唯一真源重建映射，彻底解除该合并（含传递合并）
        try:
            rebuild_merge_map_from_review(db, clear_existing=True)
        except Exception as e:
            logger.warning(f"撤销合并后重建合并映射失败（状态已改回待审核）: {e}")
    logger.info(f"Revoked review item {item_id}, status back to need_review")
    return {
        "success": True,
        "id": item_id,
        "status": "need_review",
        "message": "已撤销审核，恢复为待人工审核",
    }


def batch_revoke_reviews(db: Session, ids: List[int]) -> Dict[str, Any]:
    """批量撤销审核（逐个处理，单条失败不影响其余）。

    所有改为待审核的项一次性提交后，若其中存在曾合并的项，则统一以 review_candidate
    为唯一真源重建一次 company_merge_map（清表 + 回填），避免逐条撤销带来的 N 次重建，
    也彻底解除传递合并造成的残留映射。
    """
    results = []
    revoked = 0
    skipped = 0
    need_rebuild = False
    for item_id in ids:
        try:
            item = _fetch_review_item(db, item_id)
            if not item:
                skipped += 1
                results.append({"success": False, "id": item_id, "message": "审核项不存在"})
                continue
            if item["status"] not in _REVOCABLE_STATUSES:
                skipped += 1
                results.append({
                    "success": False,
                    "id": item_id,
                    "status": item["status"],
                    "message": "该审核项不是已审核状态，无法撤销",
                })
                continue
            if item["status"] in ("auto_merged", "merged"):
                need_rebuild = True
            _set_status(db, item_id, "need_review")
            revoked += 1
            results.append({
                "success": True,
                "id": item_id,
                "status": "need_review",
                "message": "已撤销审核，恢复为待人工审核",
            })
        except Exception as e:
            skipped += 1
            logger.warning(f"批量撤销项 {item_id} 失败: {e}")
            results.append({"success": False, "id": item_id, "message": str(e)})
    db.commit()
    if need_rebuild:
        try:
            rebuild_merge_map_from_review(db, clear_existing=True)
        except Exception as e:
            logger.warning(f"批量撤销后重建合并映射失败: {e}")
    return {
        "success": True,
        "revoked": revoked,
        "skipped": skipped,
        "total": len(ids),
        "results": results,
    }
