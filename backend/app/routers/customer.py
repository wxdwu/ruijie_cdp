"""
客户域路由（列表 + 详情）。

职责边界：本文件只做 HTTP 编排——请求参数绑定、鉴权、调用
customer service 层，并将 service 返回直接透出。所有业务查询、
SQL 拼接、响应信封（filters_applied）组装均已下沉到
app.services.customer.customer_service 与 key_account_query，
避免在路由层出现 service 级别的分支与字段映射逻辑。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.customer.customer_service import (
    CustomerNotFound,
    get_customer_statistics as query_customer_statistics,
    get_customer_statistics_by_name as query_customer_statistics_by_name,
    get_filter_options as query_filter_options,
    get_customer_detail,
    get_customer_contacts,
    get_customer_interactions,
    get_customer_opportunities,
    build_customer_ai_insight,
    list_customers as list_customers_service,
)
from app.services.customer.export_service import export_customers_excel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/customers", tags=["customers"])


# ─────────────────────────────────────────────────────────────────────────────
# Customer list endpoint（委托 customer_service 编排，路由只做编排）
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
    ``?region=广东&region=北京``）。数据源切换（重客快照 / dws_customer_360）由
    service 层统一决策。
    """
    return list_customers_service(
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
        size=size,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Filter options endpoint（委托 customer_service 查询，路由只做编排）
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/filter-options")
def get_filter_options(
    db: Session = Depends(get_db),
    special_project: List[str] = Query([], description="Scope options to projects (multi-select)"),
) -> Dict[str, List[str]]:
    """Return facets scoped to the same customer population as the list."""
    return query_filter_options(db, special_project)


# ─────────────────────────────────────────────────────────────────────────────
# Statistics endpoint（委托 customer_service 查询）
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/statistics")
def get_customer_statistics(
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """获取每个客户的联系人总数和互动数量统计，并返回汇总统计。"""
    return query_customer_statistics(db)


@router.get("/statistics/by-name")
def get_customer_statistics_by_name(
    customer_name: str = Query(..., description="客户名称（支持模糊匹配）"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """根据客户名称（模糊匹配）查询联系人和互动统计数据。"""
    return query_customer_statistics_by_name(db, customer_name)


# ─────────────────────────────────────────────────────────────────────────────
# Export endpoint（委托 export_service，排序解析下沉到 service）
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
        sort=sort,
    )

    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=customers_export.xlsx",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Customer detail endpoints（委托 customer_service，路由只做编排与异常转换）
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{customer_id}")
def get_detail(customer_id: str, db: Session = Depends(get_db)):
    """获取客户 360 详情。"""
    try:
        return get_customer_detail(db, customer_id)
    except CustomerNotFound:
        raise HTTPException(status_code=404, detail=f"客户不存在: {customer_id}")


@router.get("/{customer_id}/contacts")
def get_contacts(customer_id: str, db: Session = Depends(get_db)):
    """获取客户联系人列表。"""
    try:
        return get_customer_contacts(db, customer_id)
    except CustomerNotFound:
        raise HTTPException(status_code=404, detail=f"客户不存在: {customer_id}")


@router.get("/{customer_id}/interactions")
def get_interactions(customer_id: str, db: Session = Depends(get_db)):
    """获取客户互动记录。"""
    try:
        return get_customer_interactions(db, customer_id)
    except CustomerNotFound:
        raise HTTPException(status_code=404, detail=f"客户不存在: {customer_id}")


@router.get("/{customer_id}/opportunities")
def get_opportunities(customer_id: str, db: Session = Depends(get_db)):
    """获取客户商机列表。"""
    try:
        return get_customer_opportunities(db, customer_id)
    except CustomerNotFound:
        raise HTTPException(status_code=404, detail=f"客户不存在: {customer_id}")


@router.get("/{customer_id}/ai-insight")
def get_ai_insight(customer_id: str, db: Session = Depends(get_db)):
    """获取客户 AI 洞察（基于联系人、互动、商机的多维度分析）。"""
    try:
        return build_customer_ai_insight(db, customer_id)
    except CustomerNotFound:
        raise HTTPException(status_code=404, detail=f"客户不存在: {customer_id}")
