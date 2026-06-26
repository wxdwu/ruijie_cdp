"""
Campaign board API router.

Provides DWS-backed endpoints for the marketing campaign dashboard.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db

router = APIRouter(prefix="/api/campaign", tags=["campaign"])


FilterParts = Tuple[List[str], Dict[str, Any]]


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _campaign_filters(
    *,
    alias: str = "c",
    campaign_tag: Optional[str] = None,
    industry: Optional[str] = None,
    channel: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    stage: Optional[str] = None,
    owner: Optional[str] = None,
    keyword: Optional[str] = None,
    require_interaction_window: bool = False,
) -> FilterParts:
    where_parts: List[str] = ["1=1"]
    params: Dict[str, Any] = {}

    if campaign_tag:
        where_parts.append(f"{alias}.campaign_tag = :campaign_tag")
        params["campaign_tag"] = campaign_tag
    if industry:
        where_parts.append(f"{alias}.industry = :industry")
        params["industry"] = industry
    if stage:
        where_parts.append(f"{alias}.purchase_stage = :stage")
        params["stage"] = stage
    if owner:
        where_parts.append(f"{alias}.owner_name = :owner")
        params["owner"] = owner
    if keyword:
        where_parts.append(f"{alias}.customer_name LIKE :keyword")
        params["keyword"] = f"%{keyword}%"

    start = _parse_date(start_date)
    end = _parse_date(end_date)
    interaction_parts = [f"i.customer_name = {alias}.customer_name"]
    if channel:
        interaction_parts.append("i.channel = :channel")
        params["channel"] = channel
    if start:
        interaction_parts.append("DATE(i.event_time) >= :start_date")
        params["start_date"] = start
    if end:
        interaction_parts.append("DATE(i.event_time) <= :end_date")
        params["end_date"] = end

    if require_interaction_window or channel or start or end:
        where_parts.append(
            "EXISTS (SELECT 1 FROM dws_interaction_detail i "
            f"WHERE {' AND '.join(interaction_parts)})"
        )

    return where_parts, params


def _interaction_filters(
    *,
    alias: str = "i",
    campaign_tag: Optional[str] = None,
    industry: Optional[str] = None,
    channel: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> FilterParts:
    where_parts = [f"{alias}.customer_name IS NOT NULL", f"{alias}.customer_name != ''"]
    params: Dict[str, Any] = {}

    if campaign_tag or industry:
        customer_parts = [f"c.customer_name = {alias}.customer_name"]
        if campaign_tag:
            customer_parts.append("c.campaign_tag = :campaign_tag")
            params["campaign_tag"] = campaign_tag
        if industry:
            customer_parts.append("c.industry = :industry")
            params["industry"] = industry
        where_parts.append(
            "EXISTS (SELECT 1 FROM dws_customer_360 c "
            f"WHERE {' AND '.join(customer_parts)})"
        )
    if channel:
        where_parts.append(f"{alias}.channel = :channel")
        params["channel"] = channel

    start = _parse_date(start_date)
    end = _parse_date(end_date)
    if start:
        where_parts.append(f"DATE({alias}.event_time) >= :start_date")
        params["start_date"] = start
    if end:
        where_parts.append(f"DATE({alias}.event_time) <= :end_date")
        params["end_date"] = end

    return where_parts, params


def _where_sql(parts: List[str]) -> str:
    return " AND ".join(parts) if parts else "1=1"


def _percentage(count: int, total: int) -> float:
    return round((count / total * 100), 2) if total > 0 else 0


def _decode_jsonish(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    text_value = str(value).strip()
    if not text_value or text_value in {"null", "[]"}:
        return []
    return [item.strip().strip('"') for item in text_value.strip("[]").split(",") if item.strip()]


def _customer_tags(row: Any) -> List[str]:
    purchase_stage = getattr(row, "purchase_stage", None) or getattr(row, "stage", None)
    tags = [
        row.campaign_tag,
        f"{row.attribute}层" if row.attribute else None,
        row.industry,
        purchase_stage,
    ]
    tags.extend(_decode_jsonish(row.product_categories)[:2])
    tags.extend(_decode_jsonish(row.source_tables)[:1])
    return [str(tag) for tag in tags if tag]


def _followup_basis(row: Any) -> str:
    if row.last_interaction_time:
        return f"最近通过{row.last_interaction_channel or '未知渠道'}互动，建议结合内容兴趣跟进。"
    if row.active_opp_amount:
        return "存在在途商机金额，建议补充关键角色触达。"
    if row.interaction_count_total:
        return "已有历史互动，建议按最近主题继续推进。"
    return "暂无互动记录，建议先补充触达。"


@router.get("/filter-options")
def get_filter_options(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Return dashboard filter options from DWS tables."""

    campaigns = db.execute(text(
        "SELECT DISTINCT campaign_tag FROM dws_customer_360 "
        "WHERE campaign_tag IS NOT NULL AND campaign_tag != '' ORDER BY campaign_tag"
    )).fetchall()
    industries = db.execute(text(
        "SELECT DISTINCT industry FROM dws_customer_360 "
        "WHERE industry IS NOT NULL AND industry != '' ORDER BY industry"
    )).fetchall()
    channels = db.execute(text(
        "SELECT DISTINCT channel FROM dws_interaction_detail "
        "WHERE channel IS NOT NULL AND channel != '' ORDER BY channel"
    )).fetchall()
    dates = db.execute(text(
        "SELECT MIN(DATE(event_time)) AS min_date, MAX(DATE(event_time)) AS max_date "
        "FROM dws_interaction_detail WHERE event_time IS NOT NULL"
    )).one()

    return {
        "campaigns": [row[0] for row in campaigns],
        "industries": [row[0] for row in industries],
        "channels": [row[0] for row in channels],
        "min_date": dates.min_date.isoformat() if dates.min_date else None,
        "max_date": dates.max_date.isoformat() if dates.max_date else None,
    }


@router.get("/kpis")
def get_campaign_kpis(
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get 5 campaign KPI cards using the shared campaign filters."""

    customer_where, customer_params = _campaign_filters(
        campaign_tag=campaign_tag,
        industry=industry,
        channel=channel,
        start_date=start_date,
        end_date=end_date,
    )
    active_where, active_params = _campaign_filters(
        campaign_tag=campaign_tag,
        industry=industry,
        channel=channel,
        start_date=start_date,
        end_date=end_date,
        require_interaction_window=True,
    )

    total_customers = db.execute(
        text(f"SELECT COUNT(DISTINCT c.customer_name) FROM dws_customer_360 c WHERE {_where_sql(customer_where)}"),
        customer_params,
    ).scalar() or 0

    active_customers = db.execute(
        text(f"SELECT COUNT(DISTINCT c.customer_name) FROM dws_customer_360 c WHERE {_where_sql(active_where)}"),
        active_params,
    ).scalar() or 0

    kpi_row = db.execute(
        text(
            "SELECT "
            "COALESCE(SUM(COALESCE(NULLIF(c.active_opp_count, 0), c.funnel_opp_count, 0)), 0) AS opportunity_count, "
            "COALESCE(SUM(c.active_opp_amount), 0) AS total_amount, "
            "COUNT(DISTINCT CASE WHEN COALESCE(c.won_amount, 0) > 0 "
            " OR c.purchase_stage = '阶段6：完成采购，实现进入' THEN c.customer_name END) AS deal_customers "
            "FROM dws_customer_360 c "
            f"WHERE {_where_sql(customer_where)}"
        ),
        customer_params,
    ).one()

    return {
        "total_customers": int(total_customers),
        "active_customers": int(active_customers),
        "opportunity_count": int(kpi_row.opportunity_count or 0),
        "total_amount": float(kpi_row.total_amount or 0),
        "deal_customers": int(kpi_row.deal_customers or 0),
        "help_key": "campaign_kpis",
    }


@router.get("/funnel-distribution")
def get_funnel_distribution(
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get opportunity forecast distribution with status buckets."""

    where_parts, params = _campaign_filters(
        campaign_tag=campaign_tag,
        industry=industry,
        channel=channel,
        start_date=start_date,
        end_date=end_date,
    )
    rows = db.execute(
        text(
            "SELECT COALESCE(NULLIF(c.forecast_type, ''), '未标注') AS forecast_type, "
            "COUNT(*) AS customer_count, "
            "SUM(CASE WHEN COALESCE(c.won_amount, 0) > 0 "
            " OR c.purchase_stage = '阶段6：完成采购，实现进入' THEN 1 ELSE 0 END) AS deal_count, "
            "SUM(CASE WHEN COALESCE(c.active_opp_count, 0) > 0 OR COALESCE(c.funnel_opp_count, 0) > 0 THEN 1 ELSE 0 END) AS active_count, "
            "SUM(CASE WHEN c.purchase_stage IS NULL OR c.purchase_stage = '' THEN 1 ELSE 0 END) AS unknown_count "
            "FROM dws_customer_360 c "
            f"WHERE {_where_sql(where_parts)} "
            "GROUP BY COALESCE(NULLIF(c.forecast_type, ''), '未标注') "
            "ORDER BY customer_count DESC"
        ),
        params,
    ).fetchall()

    total = sum(int(row.customer_count or 0) for row in rows)
    categories = [
        {
            "forecast_type": row.forecast_type,
            "count": int(row.customer_count or 0),
            "active_count": int(row.active_count or 0),
            "deal_count": int(row.deal_count or 0),
            "unknown_count": int(row.unknown_count or 0),
            "percentage": _percentage(int(row.customer_count or 0), total),
        }
        for row in rows
    ]
    return {"categories": categories, "stages": categories, "total": total, "help_key": "opportunity_distribution"}


@router.get("/channel-distribution")
def get_channel_distribution(
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get channel attribution from dws_interaction_detail."""

    where_parts, params = _interaction_filters(
        campaign_tag=campaign_tag,
        industry=industry,
        channel=channel,
        start_date=start_date,
        end_date=end_date,
    )
    rows = db.execute(
        text(
            "SELECT i.channel, COUNT(*) AS count, COUNT(DISTINCT i.customer_name) AS customers "
            "FROM dws_interaction_detail i "
            f"WHERE {_where_sql(where_parts)} "
            "GROUP BY i.channel ORDER BY count DESC"
        ),
        params,
    ).fetchall()
    total = sum(int(row.count or 0) for row in rows)
    channels = [
        {
            "channel": row.channel,
            "count": int(row.count or 0),
            "customers": int(row.customers or 0),
            "percentage": _percentage(int(row.count or 0), total),
        }
        for row in rows
    ]
    return {"channels": channels, "total": total, "help_key": "channel_attribution"}


@router.get("/role-coverage")
def get_role_coverage(
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get key role coverage distribution."""

    where_parts, params = _campaign_filters(
        campaign_tag=campaign_tag,
        industry=industry,
        channel=channel,
        start_date=start_date,
        end_date=end_date,
    )
    rows = db.execute(
        text(
            "SELECT COALESCE(NULLIF(c.role_coverage, ''), '0/4') AS role_coverage, "
            "COUNT(*) AS customer_count "
            "FROM dws_customer_360 c "
            f"WHERE {_where_sql(where_parts)} "
            "GROUP BY COALESCE(NULLIF(c.role_coverage, ''), '0/4') "
            "ORDER BY customer_count DESC"
        ),
        params,
    ).fetchall()
    total = sum(int(row.customer_count or 0) for row in rows)
    roles = [
        {
            "role": row.role_coverage,
            "customer_count": int(row.customer_count or 0),
            "coverage_percentage": _percentage(int(row.customer_count or 0), total),
        }
        for row in rows
    ]
    return {"roles": roles, "total_customers": total, "help_key": "role_coverage"}


@router.get("/stage-distribution")
def get_stage_distribution(
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get purchase stage distribution."""

    where_parts, params = _campaign_filters(
        campaign_tag=campaign_tag,
        industry=industry,
        channel=channel,
        start_date=start_date,
        end_date=end_date,
    )
    rows = db.execute(
        text(
            "SELECT COALESCE(NULLIF(c.purchase_stage, ''), '未知阶段') AS stage, COUNT(*) AS count "
            "FROM dws_customer_360 c "
            f"WHERE {_where_sql(where_parts)} "
            "GROUP BY COALESCE(NULLIF(c.purchase_stage, ''), '未知阶段') "
            "ORDER BY count DESC"
        ),
        params,
    ).fetchall()
    total = sum(int(row.count or 0) for row in rows)
    stages = [
        {"stage": row.stage, "count": int(row.count or 0), "percentage": _percentage(int(row.count or 0), total)}
        for row in rows
    ]
    return {"stages": stages, "total": total, "help_key": "stage_distribution"}


@router.get("/tag-signals")
def get_tag_signals(
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Return available tag-like signals from DWS fields."""

    customer_where, customer_params = _campaign_filters(
        campaign_tag=campaign_tag,
        industry=industry,
        channel=channel,
        start_date=start_date,
        end_date=end_date,
    )
    interaction_where, interaction_params = _interaction_filters(
        campaign_tag=campaign_tag,
        industry=industry,
        channel=channel,
        start_date=start_date,
        end_date=end_date,
    )

    industry_rows = db.execute(
        text(
            "SELECT c.industry AS signal_name, COUNT(*) AS signal_count, '行业' AS signal_type "
            "FROM dws_customer_360 c "
            f"WHERE {_where_sql(customer_where)} AND c.industry IS NOT NULL AND c.industry != '' "
            "GROUP BY c.industry ORDER BY signal_count DESC LIMIT 8"
        ),
        customer_params,
    ).fetchall()
    behavior_rows = db.execute(
        text(
            "SELECT i.behavior_type AS signal_name, COUNT(*) AS signal_count, '行为/内容' AS signal_type "
            "FROM dws_interaction_detail i "
            f"WHERE {_where_sql(interaction_where)} AND i.behavior_type IS NOT NULL AND i.behavior_type != '' "
            "GROUP BY i.behavior_type ORDER BY signal_count DESC LIMIT 8"
        ),
        interaction_params,
    ).fetchall()
    signals = [
        {"signal": row.signal_name, "count": int(row.signal_count or 0), "type": row.signal_type}
        for row in [*industry_rows, *behavior_rows]
    ][:12]
    return {"signals": signals, "help_key": "tag_signals"}


@router.get("/content-effect")
def get_content_effect(
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get degraded content/topic interaction effect table."""

    where_parts, params = _interaction_filters(
        campaign_tag=campaign_tag,
        industry=industry,
        channel=channel,
        start_date=start_date,
        end_date=end_date,
    )
    rows = db.execute(
        text(
            "SELECT "
            "COALESCE(NULLIF(i.content, ''), NULLIF(i.behavior_type, ''), '未标注内容') AS content, "
            "COALESCE(NULLIF(i.behavior_type, ''), '互动事件') AS type, "
            "COUNT(*) AS touch_count, "
            "COUNT(DISTINCT i.customer_name) AS unique_customers, "
            "SUM(CASE WHEN i.behavior_type = '打开邮件' THEN 1 ELSE 0 END) AS opens, "
            "SUM(CASE WHEN i.behavior_type != '打开邮件' THEN 1 ELSE 0 END) AS clicks, "
            "SUM(CASE WHEN i.is_high_value = 1 THEN 1 ELSE 0 END) AS mql "
            "FROM dws_interaction_detail i "
            f"WHERE {_where_sql(where_parts)} "
            "GROUP BY COALESCE(NULLIF(i.content, ''), NULLIF(i.behavior_type, ''), '未标注内容'), "
            "COALESCE(NULLIF(i.behavior_type, ''), '互动事件') "
            "ORDER BY touch_count DESC LIMIT 20"
        ),
        params,
    ).fetchall()

    data = [
        {
            "content": row.content,
            "type": row.type,
            "role": "按内容主题识别",
            "content_interest": row.content,
            "product_interest": row.type,
            "touch_count": int(row.touch_count or 0),
            "unique_customers": int(row.unique_customers or 0),
            "open_rate": round((int(row.opens or 0) / max(1, int(row.touch_count or 0)) * 100), 2),
            "click_rate": round((int(row.clicks or 0) / max(1, int(row.touch_count or 0)) * 100), 2),
            "mql": int(row.mql or 0),
            "sql": 0,
            "deal": 0,
        }
        for row in rows
    ]
    return {"data": data, "help_key": "content_effect"}


@router.get("/customers-by-stage")
def get_customers_by_stage(
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    stage: Optional[str] = Query(None, description="Filter by purchase stage"),
    owner: Optional[str] = Query(None, description="Filter by owner name"),
    keyword: Optional[str] = Query(None, description="Search by customer name"),
    limit: int = Query(20, ge=1, le=100, description="Maximum customers to return"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get customers for follow-up table."""

    where_parts, params = _campaign_filters(
        campaign_tag=campaign_tag,
        industry=industry,
        channel=channel,
        start_date=start_date,
        end_date=end_date,
        stage=stage,
        owner=owner,
        keyword=keyword,
    )
    where_sql = _where_sql(where_parts)

    total = db.execute(
        text(f"SELECT COUNT(*) FROM dws_customer_360 c WHERE {where_sql}"),
        params,
    ).scalar() or 0

    rows = db.execute(
        text(
            "SELECT c.id, c.customer_name, c.campaign_tag, c.industry, c.region, c.attribute, "
            "c.purchase_stage AS stage, c.owner_name, c.intent_level, c.intent_score, "
            "c.role_coverage, c.last_interaction_time, c.last_interaction_channel, "
            "c.active_opp_amount, c.active_opp_count, c.interaction_count_total, "
            "c.product_categories, c.source_tables "
            "FROM dws_customer_360 c "
            f"WHERE {where_sql} "
            "ORDER BY c.intent_score DESC, c.active_opp_amount DESC, c.customer_name ASC "
            "LIMIT :limit"
        ),
        {**params, "limit": limit},
    ).fetchall()

    customers = [
        {
            "id": row.id,
            "stage": row.stage or "未知阶段",
            "customer_name": row.customer_name,
            "campaign_tag": row.campaign_tag,
            "industry": row.industry,
            "region": row.region,
            "owner_name": row.owner_name,
            "intent_level": row.intent_level,
            "intent_score": float(row.intent_score or 0),
            "role_coverage": row.role_coverage or "0/4",
            "last_interaction_time": row.last_interaction_time.isoformat() if row.last_interaction_time else None,
            "last_interaction_channel": row.last_interaction_channel,
            "active_opp_amount": float(row.active_opp_amount or 0),
            "active_opp_count": int(row.active_opp_count or 0),
            "interaction_count_total": int(row.interaction_count_total or 0),
            "tags": _customer_tags(row),
            "followup_basis": _followup_basis(row),
        }
        for row in rows
    ]

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for customer in customers:
        grouped.setdefault(customer["stage"], []).append(customer)

    option_where, option_params = _campaign_filters(
        campaign_tag=campaign_tag,
        industry=industry,
        channel=channel,
        start_date=start_date,
        end_date=end_date,
    )
    option_sql = _where_sql(option_where)
    stage_rows = db.execute(
        text(
            "SELECT DISTINCT c.purchase_stage FROM dws_customer_360 c "
            f"WHERE {option_sql} AND c.purchase_stage IS NOT NULL AND c.purchase_stage != '' "
            "ORDER BY c.purchase_stage"
        ),
        option_params,
    ).fetchall()
    owner_rows = db.execute(
        text(
            "SELECT DISTINCT c.owner_name FROM dws_customer_360 c "
            f"WHERE {option_sql} AND c.owner_name IS NOT NULL AND c.owner_name != '' "
            "ORDER BY c.owner_name"
        ),
        option_params,
    ).fetchall()

    return {
        "grouped": grouped,
        "flat": customers,
        "total": total,
        "filters_applied": {
            "campaign_tag": campaign_tag,
            "start_date": start_date,
            "end_date": end_date,
            "channel": channel,
            "industry": industry,
            "stage": stage,
            "owner": owner,
            "keyword": keyword,
        },
        "filter_options": {
            "stages": [row[0] for row in stage_rows],
            "owners": [row[0] for row in owner_rows],
        },
        "help_key": "customer_followup",
    }
