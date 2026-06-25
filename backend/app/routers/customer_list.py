"""
Customer list API router.

Provides endpoints for listing customers with filters, getting filter options,
and exporting customer data to Excel.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.export_service import export_customers_excel
from app.services.region_filter import REGION_OPTIONS, get_region_options

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/customers", tags=["customers"])


# ─────────────────────────────────────────────────────────────────────────────
# Customer list endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.get("")
def list_customers(
    db: Session = Depends(get_db),
    keyword: Optional[str] = Query(None, description="Search by customer_name"),
    industry: Optional[str] = Query(None, description="Filter by industry"),
    region: Optional[str] = Query(None, description="Filter by region"),
    region_keyword: Optional[str] = Query(None, description="Fuzzy search by region"),
    owner: Optional[str] = Query(None, description="Filter by owner_name"),
    owner_keyword: Optional[str] = Query(None, description="Fuzzy search by owner_name"),
    stage: Optional[str] = Query(None, description="Filter by purchase_stage"),
    intent_level: Optional[str] = Query(None, description="Filter by intent_level"),
    interaction_min: Optional[int] = Query(None, description="Minimum interaction count"),
    interaction_period: int = Query(30, description="Interaction period in days (30/60/90/180/365/1095)"),
    attribute: Optional[str] = Query(None, description="Filter by key customer rating: heavy/non_heavy"),
    channel: Optional[str] = Query(None, description="Filter by last_interaction_channel"),
    sort: Optional[str] = Query(None, description="Sort field and direction, e.g. 'intent_score desc'"),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Page size (max 100)"),
) -> Dict[str, Any]:
    """List customers with filters and pagination."""
    where_parts: List[str] = ["1=1"]
    params: Dict[str, Any] = {}

    if keyword:
        where_parts.append("customer_name LIKE :keyword")
        params["keyword"] = f"%{keyword}%"
    if industry:
        where_parts.append("industry = :industry")
        params["industry"] = industry
    if region:
        if region == "其他":
            placeholders = []
            for index, value in enumerate(item for item in REGION_OPTIONS if item != "其他"):
                key = f"standard_region_{index}"
                placeholders.append(f":{key}")
                params[key] = value
            where_parts.append(
                "(region IS NULL OR region = '' "
                f"OR region NOT IN ({', '.join(placeholders)}))"
            )
        else:
            where_parts.append("region = :region")
            params["region"] = region
    elif region_keyword:
        if region_keyword.strip() == "其他":
            placeholders = []
            for index, value in enumerate(item for item in REGION_OPTIONS if item != "其他"):
                key = f"standard_region_{index}"
                placeholders.append(f":{key}")
                params[key] = value
            where_parts.append(
                "(region IS NULL OR region = '' "
                f"OR region NOT IN ({', '.join(placeholders)}))"
            )
        else:
            where_parts.append("region LIKE :region_keyword")
            params["region_keyword"] = f"%{region_keyword}%"
    if owner:
        where_parts.append("owner_name = :owner")
        params["owner"] = owner
    elif owner_keyword:
        where_parts.append("owner_name LIKE :owner_keyword")
        params["owner_keyword"] = f"%{owner_keyword}%"
    if stage:
        where_parts.append("purchase_stage = :stage")
        params["stage"] = stage
    if intent_level:
        where_parts.append("intent_level = :intent_level")
        params["intent_level"] = intent_level
    if interaction_min is not None:
        # 使用子查询动态计算指定时间范围内的互动次数
        where_parts.append("""
            customer_name IN (
                SELECT customer_name
                FROM dws_interaction_detail
                WHERE event_time >= DATE_SUB(NOW(), INTERVAL :period DAY)
                GROUP BY customer_name
                HAVING COUNT(*) >= :interaction_min
            )
        """)
        params["interaction_min"] = interaction_min
        params["period"] = interaction_period
    if attribute == "heavy":
        where_parts.append("attribute = :heavy_attribute")
        params["heavy_attribute"] = "H"
    elif attribute == "non_heavy":
        where_parts.append("(attribute IS NULL OR attribute != :heavy_attribute)")
        params["heavy_attribute"] = "H"
    if channel:
        where_parts.append("last_interaction_channel = :channel")
        params["channel"] = channel

    where_sql = " AND ".join(where_parts)

    # Count total
    count_sql = text(f"SELECT COUNT(*) FROM dws_customer_360 WHERE {where_sql}")
    total: int = db.execute(count_sql, params).scalar() or 0

    # Sorting
    sort_by = "intent_score"
    sort_order = "DESC"
    if sort:
        parts = sort.strip().split()
        allowed_sort = {
            "customer_name", "industry", "intent_score", "interaction_count_30d",
            "interaction_count_total", "last_interaction_time", "active_opp_amount",
            "won_amount", "updated_at",
        }
        if parts[0] in allowed_sort:
            sort_by = parts[0]
        if len(parts) > 1 and parts[1].upper() == "ASC":
            sort_order = "ASC"

    # Pagination
    offset = (page - 1) * size
    data_sql = text(
        f"SELECT * FROM dws_customer_360 "
        f"WHERE {where_sql} "
        f"ORDER BY {sort_by} {sort_order} "
        f"LIMIT :limit OFFSET :offset"
    )
    params["limit"] = size
    params["offset"] = offset

    rows = db.execute(data_sql, params).mappings().all()
    items = [dict(r) for r in rows]

    filters_applied = {
        "keyword": keyword,
        "industry": industry,
        "region": region,
        "region_keyword": region_keyword,
        "owner": owner,
        "owner_keyword": owner_keyword,
        "stage": stage,
        "intent_level": intent_level,
        "interaction_min": interaction_min,
        "interaction_period": interaction_period,
        "attribute": attribute,
        "channel": channel,
        "sort": sort,
    }

    return {
        "total": total,
        "items": items,
        "filters_applied": filters_applied,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Filter options endpoint
# ─────────────────────────────────────────────────────────────────────────────

def _distinct_values(db: Session, column: str) -> List[str]:
    """Return sorted distinct non-null values for a column."""
    sql = text(
        f"SELECT DISTINCT {column} FROM dws_customer_360 "
        f"WHERE {column} IS NOT NULL AND {column} != '' "
        f"ORDER BY {column}"
    )
    rows = db.execute(sql).fetchall()
    return [r[0] for r in rows]


@router.get("/filter-options")
def get_filter_options(db: Session = Depends(get_db)) -> Dict[str, List[str]]:
    """Return distinct values for all filterable facets from dws_customer_360."""
    return {
        "industries": _distinct_values(db, "industry"),
        "regions": get_region_options(),
        "owners": _distinct_values(db, "owner_name"),
        "stages": _distinct_values(db, "purchase_stage"),
        "intent_levels": _distinct_values(db, "intent_level"),
        "channels": _distinct_values(db, "last_interaction_channel"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Statistics endpoint
# ─────────────────────────────────────────────────────────────────────────────

# 获取所有公司的联系人总数和互动总数
@router.get("/statistics")
def get_customer_statistics(
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    获取每个客户的联系人总数和互动数量统计.

    返回所有客户的统计信息，包括：
    - customer_name: 客户名称
    - contact_count: 联系人总数
    - interaction_count_total: 总互动数量
    - interaction_count_30d: 近30天互动数量
    - intent_level: 意向等级
    - purchase_stage: 采购阶段

    同时返回汇总统计信息（total_contacts, total_interactions）
    """
    # 查询 SQL - 从聚合表获取统计数据
    sql = text("""
        SELECT
            customer_name,
            contact_count,
            interaction_count_total,
            interaction_count_30d,
            intent_level,
            purchase_stage
        FROM dws_customer_360
        ORDER BY interaction_count_total DESC
    """)

    # 执行查询
    rows = db.execute(sql).mappings().all()
    items = [dict(r) for r in rows]

    # 计算汇总统计
    total_contacts = sum(item.get("contact_count", 0) or 0 for item in items)
    total_interactions = sum(item.get("interaction_count_total", 0) or 0 for item in items)

    return {
        "items": items,
        "total": len(items),
        "summary": {
            "total_contacts": total_contacts,
            "total_interactions": total_interactions,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Customer statistics by name endpoint
# ─────────────────────────────────────────────────────────────────────────────
# 根据某个公司名称获取该公司的联系人总数和互动总数
@router.get("/statistics/by-name")
def get_customer_statistics_by_name(
    customer_name: str = Query(..., description="客户名称（支持模糊匹配）"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    根据客户名称查询联系人和互动统计数据.

    通过客户名称（支持模糊匹配）查询该客户的：
    - contact_count: 联系人总数
    - interaction_count_total: 总互动数量

    返回格式：
    {
        "status": "success",
        "timestamp": "2026-06-18T10:30:00",
        "data": {
            "customer_name": "山东魏桥创业集团有限公司",
            "contact_count": 10,
            "interaction_count_total": 1092
        }
    }
    """
    # 查询 SQL - 支持模糊匹配
    sql = text("""
        SELECT
            customer_name,
            contact_count,
            interaction_count_total
        FROM dws_customer_360
        WHERE customer_name LIKE :customer_name
        LIMIT 1
    """)

    # 执行查询（支持模糊匹配）
    params = {"customer_name": f"%{customer_name}%"}
    rows = db.execute(sql, params).mappings().all()

    # 构建响应
    from datetime import datetime
    timestamp = datetime.now().isoformat()

    if not rows:
        return {
            "status": "not_found",
            "timestamp": timestamp,
            "data": None,
            "message": f"未找到客户: {customer_name}",
        }

    # 获取第一条匹配记录
    result = dict(rows[0])

    return {
        "status": "success",
        "timestamp": timestamp,
        "data": {
            "customer_name": result.get("customer_name"),
            "contact_count": result.get("contact_count", 0),
            "interaction_count_total": result.get("interaction_count_total", 0),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Export endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/export")
def export_customers(
    db: Session = Depends(get_db),
    keyword: Optional[str] = Query(None, description="Search by customer_name"),
    industry: Optional[str] = Query(None, description="Filter by industry"),
    region: Optional[str] = Query(None, description="Filter by region"),
    region_keyword: Optional[str] = Query(None, description="Fuzzy search by region"),
    owner: Optional[str] = Query(None, description="Filter by owner_name"),
    owner_keyword: Optional[str] = Query(None, description="Fuzzy search by owner_name"),
    stage: Optional[str] = Query(None, description="Filter by purchase_stage"),
    intent_level: Optional[str] = Query(None, description="Filter by intent_level"),
    interaction_min: Optional[int] = Query(None, description="Minimum interaction count"),
    interaction_period: int = Query(30, description="Interaction period in days (30/60/90/180/365/1095)"),
    attribute: Optional[str] = Query(None, description="Filter by key customer rating: heavy/non_heavy"),
    channel: Optional[str] = Query(None, description="Filter by last_interaction_channel"),
    sort: Optional[str] = Query(None, description="Sort field and direction, e.g. 'intent_score desc'"),
) -> Response:
    """Export filtered customer list as Excel file."""
    # Parse sort
    sort_by = "intent_score"
    sort_order = "DESC"
    if sort:
        parts = sort.strip().split()
        allowed_sort = {
            "customer_name", "industry", "intent_score", "interaction_count_30d",
            "interaction_count_total", "last_interaction_time", "active_opp_amount",
            "won_amount", "updated_at",
        }
        if parts[0] in allowed_sort:
            sort_by = parts[0]
        if len(parts) > 1 and parts[1].upper() == "ASC":
            sort_order = "ASC"

    excel_bytes = export_customers_excel(
        db,
        keyword=keyword,
        industry=industry,
        region=region,
        region_keyword=region_keyword,
        owner=owner,
        owner_keyword=owner_keyword,
        stage=stage,
        intent_level=intent_level,
        interaction_min=interaction_min,
        interaction_period=interaction_period,
        attribute=attribute,
        channel=channel,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=customers_export.xlsx",
        },
    )
