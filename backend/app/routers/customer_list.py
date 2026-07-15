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
from app.services.channel_classification import available_channel_options
from app.services.customer_service import get_customer_list
from app.services.export_service import export_customers_excel
from app.services.key_account_query import (
    KEY_ACCOUNT_SOURCE_PROJECT,
    KEY_ACCOUNT_TABLE,
    count_key_accounts,
    fetch_key_accounts,
)
from app.services.region_filter import available_region_options

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/customers", tags=["customers"])

def _list_key_accounts(
    db: Session,
    *,
    keyword: Optional[List[str]],
    industry: Optional[List[str]],
    region: Optional[List[str]],
    region_keyword: Optional[str],
    owner: Optional[List[str]],
    owner_keyword: Optional[str],
    stage: Optional[str],
    intent_level: Optional[str],
    interaction_min: Optional[int],
    interaction_period: int,
    channel: Optional[List[str]],
    sort: Optional[str],
    page: int,
    size: int,
) -> Dict[str, Any]:
    """Return the latest key-account snapshot enriched from customer 360."""
    query_filters = {
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
        "channel": channel,
    }
    total = count_key_accounts(db, **query_filters)
    items = fetch_key_accounts(
        db,
        page=page,
        size=size,
        sort=sort,
        **query_filters,
    )

    return {
        "total": total,
        "items": items,
        "filters_applied": {
            "keyword": keyword,
            "special_project": ["重客"],
            "industry": industry,
            "region": region,
            "region_keyword": region_keyword,
            "owner": owner,
            "owner_keyword": owner_keyword,
            "stage": stage,
            "intent_level": intent_level,
            "interaction_min": interaction_min,
            "interaction_period": interaction_period,
            "attribute": "heavy",
            "channel": channel,
            "sort": sort,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Customer list endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.get("")
def list_customers(
    db: Session = Depends(get_db),
    keyword: List[str] = Query([], description="Filter by customer_name (multi-select)"),
    special_project: List[str] = Query([], description="Filter by campaign_tag (multi-select)"),
    industry: List[str] = Query([], description="Filter by industry (multi-select)"),
    region: List[str] = Query([], description="Filter by region (multi-select)"),
    region_keyword: Optional[str] = Query(None, description="Fuzzy search by region"),
    owner: List[str] = Query([], description="Filter by owner_name (multi-select)"),
    owner_keyword: Optional[str] = Query(None, description="Fuzzy search by owner_name"),
    stage: Optional[str] = Query(None, description="Filter by purchase_stage"),
    intent_level: Optional[str] = Query(None, description="Filter by intent_level"),
    interaction_min: Optional[int] = Query(None, description="Minimum interaction count"),
    interaction_period: int = Query(30, description="Interaction period in days (30/60/90/180/365/1095)"),
    attribute: Optional[str] = Query(None, description="Filter by key customer rating: heavy/non_heavy"),
    channel: List[str] = Query([], description="Filter by last_interaction_channel (multi-select)"),
    sort: Optional[str] = Query(None, description="Sort field and direction, e.g. 'intent_score desc'"),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Page size (max 100)"),
) -> Dict[str, Any]:
    """List customers with filters and pagination.

    专项/行业/区域/负责人/互动方式均支持多选（重复 query 参数，例如
    ``?region=广东&region=北京``）。
    """
    if len(special_project) == 1 and special_project[0] == "重客":
        return _list_key_accounts(
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
            channel=channel,
            sort=sort,
            page=page,
            size=size,
        )

    return get_customer_list(
        db,
        keyword=keyword,
        special_project=special_project,
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
        sort=sort,
        page=page,
        page_size=size,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Filter options endpoint
# ─────────────────────────────────────────────────────────────────────────────

_FILTER_OPTION_COLUMNS = (
    "industry",
    "region",
    "owner_name",
    "purchase_stage",
    "intent_level",
)


def _filter_option_rows(db: Session, special_projects: List[str]) -> List[Any]:
    """返回所选专项客户群体的合并列（用于下拉选项去重）。"""
    columns = ", ".join(f"c.{column}" for column in _FILTER_OPTION_COLUMNS)
    rows: List[Any] = []
    # 重客：来自重客快照表，客户名称优先取重客名称（未进入彩光的重客也能作为候选项）
    if "重客" in special_projects:
        ka_sql = text(
            f"""
            SELECT {columns}, COALESCE(ka.`重客名称`, c.customer_name) AS customer_name
            FROM {KEY_ACCOUNT_TABLE} ka
            LEFT JOIN dws_customer_360 c
              ON c.customer_name = ka.`重客名称`
             AND c.campaign_tag = :filter_source_project
            WHERE ka.`time` = (SELECT MAX(`time`) FROM {KEY_ACCOUNT_TABLE})
            """
        )
        rows.extend(
            db.execute(ka_sql, {"filter_source_project": KEY_ACCOUNT_SOURCE_PROJECT}).mappings().all()
        )
    # 其余专项：来自 dws_customer_360
    others = [p for p in special_projects if p != "重客"]
    if others:
        other_sql = text(
            f"SELECT {columns}, c.customer_name AS customer_name FROM dws_customer_360 c "
            f"WHERE c.campaign_tag IN :filter_other_projects"
        )
        rows.extend(
            db.execute(other_sql, {"filter_other_projects": tuple(others)}).mappings().all()
        )
    # 未选任何专项：返回全部客户
    if not special_projects:
        all_sql = text(f"SELECT {columns}, c.customer_name AS customer_name FROM dws_customer_360 c")
        rows.extend(db.execute(all_sql).mappings().all())
    return rows


def _facet_values(rows: List[Any], column: str) -> List[str]:
    return sorted({str(row.get(column)).strip() for row in rows if row.get(column) not in (None, "")})


def _channel_option_rows(db: Session, special_projects: List[str]) -> List[Any]:
    params: Dict[str, Any] = {}
    clauses: List[str] = []
    if "重客" in special_projects:
        clauses.append(
            f"""
            SELECT DISTINCT interaction.channel
            FROM dws_interaction_detail interaction
            INNER JOIN {KEY_ACCOUNT_TABLE} ka
              ON ka.`重客名称` = interaction.customer_name
             AND ka.`time` = (SELECT MAX(`time`) FROM {KEY_ACCOUNT_TABLE})
            WHERE interaction.channel IS NOT NULL AND TRIM(interaction.channel) != ''
            """
        )
    others = [p for p in special_projects if p != "重客"]
    if others:
        clauses.append(
            """
            SELECT DISTINCT interaction.channel
            FROM dws_interaction_detail interaction
            INNER JOIN dws_customer_360 c ON c.customer_name = interaction.customer_name
            WHERE c.campaign_tag IN :channel_other_projects
              AND interaction.channel IS NOT NULL AND TRIM(interaction.channel) != ''
            """
        )
        params["channel_other_projects"] = tuple(others)
    if not special_projects:
        clauses.append(
            """
            SELECT DISTINCT interaction.channel
            FROM dws_interaction_detail interaction
            WHERE interaction.channel IS NOT NULL AND TRIM(interaction.channel) != ''
            """
        )
    if not clauses:
        return []
    sql = text(" UNION ".join(clauses))
    return db.execute(sql, params).mappings().all()


@router.get("/filter-options")
def get_filter_options(
    db: Session = Depends(get_db),
    special_project: List[str] = Query([], description="Scope options to projects (multi-select)"),
) -> Dict[str, List[str]]:
    """Return facets scoped to the same customer population as the list."""
    rows = _filter_option_rows(db, special_project)
    channel_rows = _channel_option_rows(db, special_project)
    return {
        "industries": _facet_values(rows, "industry"),
        "regions": available_region_options(row.get("region") for row in rows),
        "owners": _facet_values(rows, "owner_name"),
        "keywords": _facet_values(rows, "customer_name"),
        "stages": _facet_values(rows, "purchase_stage"),
        "intent_levels": _facet_values(rows, "intent_level"),
        "channels": available_channel_options(row.get("channel") for row in channel_rows),
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
    keyword: List[str] = Query([], description="Filter by customer_name (multi-select)"),
    special_project: List[str] = Query([], description="Filter by campaign_tag (multi-select)"),
    industry: List[str] = Query([], description="Filter by industry (multi-select)"),
    region: List[str] = Query([], description="Filter by region (multi-select)"),
    region_keyword: Optional[str] = Query(None, description="Fuzzy search by region"),
    owner: List[str] = Query([], description="Filter by owner_name (multi-select)"),
    owner_keyword: Optional[str] = Query(None, description="Fuzzy search by owner_name"),
    stage: Optional[str] = Query(None, description="Filter by purchase_stage"),
    intent_level: Optional[str] = Query(None, description="Filter by intent_level"),
    interaction_min: Optional[int] = Query(None, description="Minimum interaction count"),
    interaction_period: int = Query(30, description="Interaction period in days (30/60/90/180/365/1095)"),
    attribute: Optional[str] = Query(None, description="Filter by key customer rating: heavy/non_heavy"),
    channel: List[str] = Query([], description="Filter by last_interaction_channel (multi-select)"),
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
        special_project=special_project,
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
