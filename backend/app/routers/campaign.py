"""
Campaign board API router.

仅做 HTTP 编排：参数校验、委托 campaign_service 执行 DWS 查询与聚合、统一返回。
所有 SQL 拼装、聚合与响应整形均在 app.services.campaign.campaign_service 内。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.campaign.campaign_service import (
    get_campaign_bootstrap,
    get_campaign_kpis,
    get_campaign_overview,
    get_channel_distribution,
    get_content_effect,
    get_customers_by_stage,
    get_filter_options,
    get_funnel_distribution,
    get_role_coverage,
    get_stage_distribution,
    get_tag_signals,
)

router = APIRouter(prefix="/api/campaign", tags=["campaign"])


@router.get("/filter-options")
def get_filter_options_endpoint(db: Session = Depends(get_db)):
    return get_filter_options(db)


@router.get("/kpis")
def get_campaign_kpis_endpoint(
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    db: Session = Depends(get_db),
):
    return get_campaign_kpis(
        db, campaign_tag=campaign_tag, start_date=start_date,
        end_date=end_date, channel=channel, industry=industry,
    )


@router.get("/funnel-distribution")
def get_funnel_distribution_endpoint(
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    db: Session = Depends(get_db),
):
    return get_funnel_distribution(
        db, campaign_tag=campaign_tag, start_date=start_date,
        end_date=end_date, channel=channel, industry=industry,
    )


@router.get("/channel-distribution")
def get_channel_distribution_endpoint(
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    db: Session = Depends(get_db),
):
    return get_channel_distribution(
        db, campaign_tag=campaign_tag, start_date=start_date,
        end_date=end_date, channel=channel, industry=industry,
    )


@router.get("/role-coverage")
def get_role_coverage_endpoint(
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    db: Session = Depends(get_db),
):
    return get_role_coverage(
        db, campaign_tag=campaign_tag, start_date=start_date,
        end_date=end_date, channel=channel, industry=industry,
    )


@router.get("/stage-distribution")
def get_stage_distribution_endpoint(
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    db: Session = Depends(get_db),
):
    return get_stage_distribution(
        db, campaign_tag=campaign_tag, start_date=start_date,
        end_date=end_date, channel=channel, industry=industry,
    )


@router.get("/tag-signals")
def get_tag_signals_endpoint(
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    db: Session = Depends(get_db),
):
    return get_tag_signals(
        db, campaign_tag=campaign_tag, start_date=start_date,
        end_date=end_date, channel=channel, industry=industry,
    )


@router.get("/content-effect")
def get_content_effect_endpoint(
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    db: Session = Depends(get_db),
):
    return get_content_effect(
        db, campaign_tag=campaign_tag, start_date=start_date,
        end_date=end_date, channel=channel, industry=industry,
    )


@router.get("/overview")
def get_campaign_overview_endpoint(
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    include_content: bool = True,
    include_global_filter_options: bool = False,
    db: Session = Depends(get_db),
):
    return get_campaign_overview(
        db, campaign_tag=campaign_tag, start_date=start_date,
        end_date=end_date, channel=channel, industry=industry,
        include_content=include_content,
        include_global_filter_options=include_global_filter_options,
    )


@router.get("/customers-by-stage")
def get_customers_by_stage_endpoint(
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
    return get_customers_by_stage(
        db, campaign_tag=campaign_tag, start_date=start_date, end_date=end_date,
        channel=channel, industry=industry, stage=stage, owner=owner, keyword=keyword,
        page=page, page_size=page_size, include_filter_options=include_filter_options,
    )


@router.get("/bootstrap")
def get_campaign_bootstrap_endpoint(
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    page: int = Query(1, ge=1, description="Initial customer page"),
    page_size: int = Query(10, ge=1, le=100, description="Initial customer page size"),
    db: Session = Depends(get_db),
):
    return get_campaign_bootstrap(
        db, campaign_tag=campaign_tag, start_date=start_date, end_date=end_date,
        channel=channel, industry=industry, page=page, page_size=page_size,
    )
