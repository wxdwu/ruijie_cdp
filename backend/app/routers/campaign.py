"""
Campaign board API router.

仅做 HTTP 编排：参数校验、委托 campaign_service 执行 DWS 查询与聚合、统一返回。
所有 SQL 拼装、聚合与响应整形均在 app.services.campaign.campaign_service 内。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.cache.campaign_cache import (
    apply_campaign_cache_headers,
    campaign_cache_coordinator,
)
from app.database import get_db
from app.services.campaign.campaign_service import (
    get_campaign_kpis,
    get_channel_distribution,
    get_funnel_distribution,
    get_role_coverage,
    get_stage_distribution,
    get_tag_signals,
)

router = APIRouter(prefix="/api/campaign", tags=["campaign"])


def _apply_uncached_headers(response: Response) -> None:
    """旧的拆分接口保留直查口径，但仍返回统一观测响应头。"""
    response.headers["X-Cache"] = "BYPASS"
    response.headers["X-Cache-TTL"] = "0"
    response.headers["X-Data-Generation"] = str(
        campaign_cache_coordinator.get_active_generation()
    )


@router.get("/filter-options")
def get_filter_options_endpoint(
    response: Response,
    db: Session = Depends(get_db),
):
    result = campaign_cache_coordinator.get_filter_options(db)
    apply_campaign_cache_headers(response, result)
    return result.value


@router.get("/kpis")
def get_campaign_kpis_endpoint(
    response: Response,
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    db: Session = Depends(get_db),
):
    result = get_campaign_kpis(
        db, campaign_tag=campaign_tag, start_date=start_date,
        end_date=end_date, channel=channel, industry=industry,
    )
    _apply_uncached_headers(response)
    return result


@router.get("/funnel-distribution")
def get_funnel_distribution_endpoint(
    response: Response,
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    db: Session = Depends(get_db),
):
    result = get_funnel_distribution(
        db, campaign_tag=campaign_tag, start_date=start_date,
        end_date=end_date, channel=channel, industry=industry,
    )
    _apply_uncached_headers(response)
    return result


@router.get("/channel-distribution")
def get_channel_distribution_endpoint(
    response: Response,
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    db: Session = Depends(get_db),
):
    result = get_channel_distribution(
        db, campaign_tag=campaign_tag, start_date=start_date,
        end_date=end_date, channel=channel, industry=industry,
    )
    _apply_uncached_headers(response)
    return result


@router.get("/role-coverage")
def get_role_coverage_endpoint(
    response: Response,
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    db: Session = Depends(get_db),
):
    result = get_role_coverage(
        db, campaign_tag=campaign_tag, start_date=start_date,
        end_date=end_date, channel=channel, industry=industry,
    )
    _apply_uncached_headers(response)
    return result


@router.get("/stage-distribution")
def get_stage_distribution_endpoint(
    response: Response,
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    db: Session = Depends(get_db),
):
    result = get_stage_distribution(
        db, campaign_tag=campaign_tag, start_date=start_date,
        end_date=end_date, channel=channel, industry=industry,
    )
    _apply_uncached_headers(response)
    return result


@router.get("/tag-signals")
def get_tag_signals_endpoint(
    response: Response,
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    db: Session = Depends(get_db),
):
    result = get_tag_signals(
        db, campaign_tag=campaign_tag, start_date=start_date,
        end_date=end_date, channel=channel, industry=industry,
    )
    _apply_uncached_headers(response)
    return result


@router.get("/content-effect")
def get_content_effect_endpoint(
    response: Response,
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    db: Session = Depends(get_db),
):
    result = campaign_cache_coordinator.get_content_effect(
        db, campaign_tag=campaign_tag, start_date=start_date,
        end_date=end_date, channel=channel, industry=industry,
    )
    apply_campaign_cache_headers(response, result)
    return result.value


@router.get("/overview")
def get_campaign_overview_endpoint(
    response: Response,
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    include_content: bool = True,
    include_global_filter_options: bool = False,
    db: Session = Depends(get_db),
):
    result = campaign_cache_coordinator.get_overview(
        db, campaign_tag=campaign_tag, start_date=start_date,
        end_date=end_date, channel=channel, industry=industry,
        include_content=include_content,
        include_global_filter_options=include_global_filter_options,
    )
    apply_campaign_cache_headers(response, result)
    return result.value


@router.get("/customers-by-stage")
def get_customers_by_stage_endpoint(
    response: Response,
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    stage: Optional[str] = Query(None, description="Filter by purchase stage"),
    owner: Optional[str] = Query(None, description="Filter by owner name"),
    keyword: Optional[str] = Query(None, description="Search by customer name"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=100, description="Customers per page"),
    include_filter_options: bool = Query(True, description="Include stage and owner options"),
    db: Session = Depends(get_db),
):
    result = campaign_cache_coordinator.get_customers_by_stage(
        db, campaign_tag=campaign_tag, start_date=start_date, end_date=end_date,
        channel=channel, industry=industry, stage=stage, owner=owner, keyword=keyword,
        page=page, page_size=page_size, include_filter_options=include_filter_options,
    )
    apply_campaign_cache_headers(response, result)
    return result.value


@router.get("/bootstrap")
def get_campaign_bootstrap_endpoint(
    response: Response,
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    page: int = Query(1, ge=1, description="Initial customer page"),
    page_size: int = Query(10, ge=1, le=100, description="Initial customer page size"),
    db: Session = Depends(get_db),
):
    result = campaign_cache_coordinator.get_bootstrap(
        db, campaign_tag=campaign_tag, start_date=start_date, end_date=end_date,
        channel=channel, industry=industry, page=page, page_size=page_size,
    )
    apply_campaign_cache_headers(response, result)
    return result.value
