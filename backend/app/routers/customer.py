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

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.cache import CacheResult, cache_service, customer_name_catalog
from app.services.customer.customer_service import (
    CustomerNotFound,
    get_customer_statistics as query_customer_statistics,
    get_customer_statistics_by_name as query_customer_statistics_by_name,
    get_filter_options as query_filter_options,
    get_customer_detail,
    get_customer_contacts,
    get_customer_interactions,
    get_customer_opportunities,
    get_all_customer_names,
    get_customer_name_options,
    get_customer_name_suggestions,
    build_customer_ai_insight,
    list_customers as list_customers_service,
)
from app.services.customer.export_service import export_customers_excel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/customers", tags=["customers"])

_SUPPORTED_FILTER_PROJECTS = {"企业彩光ICT", "重客"}
_FILTER_OPTIONS_TTL_SECONDS = 60 * 60
_DEFAULT_LIST_TTL_SECONDS = 2 * 60
_NAME_SUGGESTION_TTL_SECONDS = 2 * 60
_EMPTY_NAME_SUGGESTION_TTL_SECONDS = 30
_NAME_CATALOG_TTL_SECONDS = 60 * 60


def _set_cache_headers(response: Response, result: CacheResult) -> None:
    response.headers["X-Cache"] = result.status
    response.headers["X-Cache-TTL"] = str(max(0, result.ttl_seconds))


def _cacheable_project_scope(special_project: List[str]) -> bool:
    return len(special_project) <= len(_SUPPORTED_FILTER_PROJECTS) and set(special_project).issubset(
        _SUPPORTED_FILTER_PROJECTS
    )


def _warm_customer_name_catalog(special_project: List[str]) -> None:
    """Build a scope catalog after the cold page has already been returned."""
    db = SessionLocal()
    try:
        customer_name_catalog.get_page(
            special_project=special_project,
            query="",
            offset=0,
            limit=1,
            ttl_seconds=_NAME_CATALOG_TTL_SECONDS,
            catalog_loader=lambda: get_all_customer_names(
                db,
                special_project=special_project,
            ),
            page_loader=lambda: get_customer_name_options(
                db,
                special_project=special_project,
                offset=0,
                limit=1,
            ),
            cacheable=_cacheable_project_scope(special_project),
            endpoint="/api/customers/name-options:warm",
        )
    finally:
        db.close()


def _is_default_customer_page(
    *,
    keyword: List[str],
    special_project: List[str],
    industry: List[str],
    region: List[str],
    region_keyword: Optional[str],
    owner: List[str],
    owner_keyword: Optional[str],
    stage: Optional[str],
    intent_level: Optional[str],
    interaction_min: Optional[int],
    interaction_period: int,
    attribute: Optional[str],
    channel: List[str],
    sort: Optional[str],
    page: int,
    size: int,
) -> bool:
    return (
        special_project == ["企业彩光ICT"]
        and not keyword
        and not industry
        and not region
        and not region_keyword
        and not owner
        and not owner_keyword
        and not stage
        and not intent_level
        and interaction_min is None
        and interaction_period == 30
        and not attribute
        and not channel
        and not sort
        and page == 1
        and size == 20
    )


# ─────────────────────────────────────────────────────────────────────────────
# Customer list endpoint（委托 customer_service 编排，路由只做编排）
# ─────────────────────────────────────────────────────────────────────────────

@router.get("")
def list_customers(
    response: Response,
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
    cache_params = {
        "keyword": keyword,
        "special_project": special_project,
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
        "page": page,
        "size": size,
    }

    def load_customer_page() -> Dict[str, Any]:
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

    result = cache_service.get_or_load_json(
        "customer:list-default",
        cache_params,
        _DEFAULT_LIST_TTL_SECONDS,
        load_customer_page,
        cacheable=_is_default_customer_page(**cache_params),
        endpoint="/api/customers",
    )
    _set_cache_headers(response, result)
    return result.value


# ─────────────────────────────────────────────────────────────────────────────
# Filter options endpoint（委托 customer_service 查询，路由只做编排）
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/filter-options")
def get_filter_options(
    response: Response,
    db: Session = Depends(get_db),
    special_project: List[str] = Query([], description="Scope options to projects (multi-select)"),
) -> Dict[str, List[str]]:
    """Return facets scoped to the same customer population as the list."""
    result = cache_service.get_or_load_json(
        "customer:filter-options",
        {"special_project": special_project},
        _FILTER_OPTIONS_TTL_SECONDS,
        lambda: query_filter_options(db, special_project),
        cacheable=_cacheable_project_scope(special_project),
        endpoint="/api/customers/filter-options",
    )
    _set_cache_headers(response, result)
    return result.value


@router.get("/name-suggestions")
def get_name_suggestions(
    response: Response,
    q: str = Query(..., min_length=1, max_length=100, description="Customer-name prefix"),
    special_project: List[str] = Query([], description="Scope suggestions to projects"),
    limit: int = Query(30, ge=1, le=50),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Return a bounded customer-name prefix search for the remote multi-select."""
    normalized_query = q.strip()
    if not normalized_query:
        raise HTTPException(status_code=422, detail="q must contain a non-whitespace character")
    result = cache_service.get_or_load_json(
        "customer:name-suggest",
        {
            "q": normalized_query.casefold(),
            "special_project": special_project,
            "limit": limit,
        },
        _NAME_SUGGESTION_TTL_SECONDS,
        lambda: get_customer_name_suggestions(
            db,
            query=normalized_query,
            special_project=special_project,
            limit=limit,
        ),
        cacheable=_cacheable_project_scope(special_project),
        empty_ttl_seconds=_EMPTY_NAME_SUGGESTION_TTL_SECONDS,
        endpoint="/api/customers/name-suggestions",
    )
    _set_cache_headers(response, result)
    return result.value


@router.get("/name-options")
def get_name_options(
    response: Response,
    background_tasks: BackgroundTasks,
    q: Optional[str] = Query(None, max_length=100, description="Optional customer-name prefix"),
    special_project: List[str] = Query([], description="Scope options to projects"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=50),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Browse/search the Redis-backed full customer-name catalog by page."""
    normalized_query = (q or "").strip()
    result = customer_name_catalog.get_page(
        special_project=special_project,
        query=normalized_query,
        offset=offset,
        limit=limit,
        ttl_seconds=_NAME_CATALOG_TTL_SECONDS,
        catalog_loader=lambda: get_all_customer_names(
            db,
            special_project=special_project,
        ),
        page_loader=lambda: get_customer_name_options(
            db,
            query=normalized_query,
            special_project=special_project,
            offset=offset,
            limit=limit,
        ),
        defer_build=lambda: background_tasks.add_task(
            _warm_customer_name_catalog,
            list(special_project),
        ),
        cacheable=_cacheable_project_scope(special_project),
    )
    _set_cache_headers(response, result)
    return result.value


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
