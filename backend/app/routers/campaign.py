"""
Campaign board API router.

Provides DWS-backed endpoints for the marketing campaign dashboard.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.database.engine import get_session_factory
from app.services.common.channel_classification import (
    CHANNEL_FILTER_ORDER,
    add_channel_filter,
    channel_group_case,
)
from app.services.customer.key_account_query import KEY_ACCOUNT_SOURCE_PROJECT, KEY_ACCOUNT_TABLE

router = APIRouter(prefix="/api/campaign", tags=["campaign"])
logger = logging.getLogger(__name__)


FilterParts = Tuple[List[str], Dict[str, Any]]
KEY_ACCOUNT_CAMPAIGN = "重客"


def _is_key_account_campaign(campaign_tag: Optional[str]) -> bool:
    return campaign_tag == KEY_ACCOUNT_CAMPAIGN


def _customer_scope_sql(campaign_tag: Optional[str]) -> str:
    """Return the customer population used by campaign aggregates."""
    if not _is_key_account_campaign(campaign_tag):
        return "dws_customer_360 c"
    return (
        "(SELECT `重客名称`, MIN(`重客编码`) AS `重客编码` "
        f"FROM {KEY_ACCOUNT_TABLE} "
        f"WHERE `time` = (SELECT MAX(`time`) FROM {KEY_ACCOUNT_TABLE}) "
        "AND `重客名称` IS NOT NULL AND TRIM(`重客名称`) != '' "
        "GROUP BY `重客名称`) ka "
        "LEFT JOIN dws_customer_360 c "
        "ON c.customer_name = ka.`重客名称` "
        "AND c.campaign_tag = :key_account_source_project"
    )


def _customer_name_sql(campaign_tag: Optional[str]) -> str:
    if _is_key_account_campaign(campaign_tag):
        return "COALESCE(c.customer_name, ka.`重客名称`)"
    return "c.customer_name"


def _campaign_label_sql(campaign_tag: Optional[str]) -> str:
    if _is_key_account_campaign(campaign_tag):
        return "'重客'"
    return "c.campaign_tag"


def _campaign_options(values: List[str]) -> List[str]:
    campaigns = sorted({value for value in values if value and value != KEY_ACCOUNT_CAMPAIGN})
    campaigns.append(KEY_ACCOUNT_CAMPAIGN)
    return campaigns


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _append_time_window(
    where_parts: List[str],
    params: Dict[str, Any],
    *,
    column: str,
    start_date: Optional[str],
    end_date: Optional[str],
) -> None:
    """Append an index-friendly inclusive date window as a half-open range."""
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    if start:
        where_parts.append(f"{column} >= :start_date")
        params["start_date"] = start
    if end:
        where_parts.append(f"{column} < :end_exclusive")
        params["end_exclusive"] = end + timedelta(days=1)


def _elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 2)


def _log_timing(endpoint: str, started_at: float, **query_ms: float) -> None:
    details = " ".join(f"{name}_ms={value:.2f}" for name, value in query_ms.items())
    logger.info(
        "campaign_timing endpoint=%s total_ms=%.2f%s%s",
        endpoint,
        _elapsed_ms(started_at),
        " " if details else "",
        details,
    )


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
    customer_name = _customer_name_sql(campaign_tag)

    if _is_key_account_campaign(campaign_tag):
        params["key_account_source_project"] = KEY_ACCOUNT_SOURCE_PROJECT
    elif campaign_tag:
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
        where_parts.append(f"{customer_name} LIKE :keyword")
        params["keyword"] = f"%{keyword}%"

    interaction_parts = [f"i.customer_name = {customer_name}"]
    add_channel_filter(
        interaction_parts,
        params,
        column="i.channel",
        channel=channel,
    )
    _append_time_window(
        interaction_parts,
        params,
        column="i.event_time",
        start_date=start_date,
        end_date=end_date,
    )

    if require_interaction_window or channel or _parse_date(start_date) or _parse_date(end_date):
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

    if _is_key_account_campaign(campaign_tag):
        where_parts.append(
            f"EXISTS (SELECT 1 FROM {KEY_ACCOUNT_TABLE} ka "
            f"WHERE ka.`time` = (SELECT MAX(`time`) FROM {KEY_ACCOUNT_TABLE}) "
            f"AND ka.`重客名称` = {alias}.customer_name)"
        )
        if industry:
            where_parts.append(
                "EXISTS (SELECT 1 FROM dws_customer_360 c "
                f"WHERE c.customer_name = {alias}.customer_name "
                "AND c.campaign_tag = :key_account_source_project "
                "AND c.industry = :industry)"
            )
            params["key_account_source_project"] = KEY_ACCOUNT_SOURCE_PROJECT
            params["industry"] = industry
    elif campaign_tag or industry:
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
    add_channel_filter(
        where_parts,
        params,
        column=f"{alias}.channel",
        channel=channel,
    )

    _append_time_window(
        where_parts,
        params,
        column=f"{alias}.event_time",
        start_date=start_date,
        end_date=end_date,
    )

    return where_parts, params


def _where_sql(parts: List[str]) -> str:
    return " AND ".join(parts) if parts else "1=1"


def _percentage(count: int, total: int) -> float:
    return round((count / total * 100), 2) if total > 0 else 0


def _date_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


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
    started_at = time.perf_counter()

    query_started = time.perf_counter()
    customer_options = db.execute(text(
        "SELECT 'campaign' AS option_type, campaign_tag AS option_value "
        "FROM dws_customer_360 "
        "WHERE campaign_tag IS NOT NULL AND campaign_tag != '' GROUP BY campaign_tag "
        "UNION ALL "
        "SELECT 'industry', industry "
        "FROM dws_customer_360 "
        "WHERE industry IS NOT NULL AND industry != '' GROUP BY industry"
    )).fetchall()
    customers_ms = _elapsed_ms(query_started)

    query_started = time.perf_counter()
    channel_params: Dict[str, Any] = {}
    channel_group = channel_group_case(
        "i.channel",
        channel_params,
        prefix="filter_channel",
    )
    channel_rows = db.execute(text(
        f"SELECT {channel_group} AS channel FROM dws_interaction_detail i "
        "WHERE i.channel IS NOT NULL AND TRIM(i.channel) != '' "
        f"GROUP BY {channel_group}"
    ), channel_params).fetchall()
    channels_ms = _elapsed_ms(query_started)

    query_started = time.perf_counter()
    dates = db.execute(text(
        "SELECT "
        "(SELECT event_time FROM dws_interaction_detail "
        " WHERE event_time IS NOT NULL ORDER BY event_time ASC LIMIT 1) AS min_date, "
        "(SELECT event_time FROM dws_interaction_detail "
        " WHERE event_time IS NOT NULL ORDER BY event_time DESC LIMIT 1) AS max_date"
    )).one()
    dates_ms = _elapsed_ms(query_started)

    campaigns = _campaign_options([
        row.option_value for row in customer_options if row.option_type == "campaign"
    ])
    industries = sorted(row.option_value for row in customer_options if row.option_type == "industry")
    available_channels = {row.channel for row in channel_rows if row.channel}
    channels = [channel for channel in CHANNEL_FILTER_ORDER if channel in available_channels]
    result = {
        "campaigns": campaigns,
        "industries": industries,
        "channels": channels,
        "min_date": _date_iso(dates.min_date),
        "max_date": _date_iso(dates.max_date),
    }
    _log_timing(
        "filter-options",
        started_at,
        customers=customers_ms,
        channels=channels_ms,
        dates=dates_ms,
    )

    return result


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
    customer_scope = _customer_scope_sql(campaign_tag)
    customer_name = _customer_name_sql(campaign_tag)

    total_customer_where, total_customer_params = _campaign_filters(
        campaign_tag=campaign_tag,
        industry=industry,
    )
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
        text(f"SELECT COUNT(DISTINCT {customer_name}) FROM {customer_scope} WHERE {_where_sql(total_customer_where)}"),
        total_customer_params,
    ).scalar() or 0

    active_customers = db.execute(
        text(f"SELECT COUNT(DISTINCT {customer_name}) FROM {customer_scope} WHERE {_where_sql(active_where)}"),
        active_params,
    ).scalar() or 0

    kpi_row = db.execute(
        text(
            "SELECT "
            "COALESCE(SUM(COALESCE(NULLIF(c.active_opp_count, 0), c.funnel_opp_count, 0)), 0) AS opportunity_count, "
            "COALESCE(SUM(c.active_opp_amount), 0) AS total_amount, "
            "COUNT(DISTINCT CASE WHEN COALESCE(c.won_amount, 0) > 0 "
            f" OR c.purchase_stage = '阶段6：完成采购，实现进入' THEN {customer_name} END) AS deal_customers "
            f"FROM {customer_scope} "
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
    customer_scope = _customer_scope_sql(campaign_tag)

    where_parts, params = _campaign_filters(
        campaign_tag=campaign_tag,
        industry=industry,
    )
    rows = db.execute(
        text(
            "SELECT COALESCE(NULLIF(c.forecast_type, ''), '未标注') AS forecast_type, "
            "COUNT(*) AS customer_count, "
            "SUM(CASE WHEN COALESCE(c.won_amount, 0) > 0 "
            " OR c.purchase_stage = '阶段6：完成采购，实现进入' THEN 1 ELSE 0 END) AS deal_count, "
            "SUM(CASE WHEN COALESCE(c.active_opp_count, 0) > 0 OR COALESCE(c.funnel_opp_count, 0) > 0 THEN 1 ELSE 0 END) AS active_count, "
            "SUM(CASE WHEN c.purchase_stage IS NULL OR c.purchase_stage = '' THEN 1 ELSE 0 END) AS unknown_count "
            f"FROM {customer_scope} "
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
    """Get customer-level channel attribution from dws_customer_360."""
    customer_scope = _customer_scope_sql(campaign_tag)
    customer_name = _customer_name_sql(campaign_tag)

    where_parts, params = _campaign_filters(
        campaign_tag=campaign_tag,
        industry=industry,
    )
    channel_group = channel_group_case("c.last_interaction_channel", params)
    rows = db.execute(
        text(
            f"SELECT {channel_group} AS channel, "
            f"COUNT(DISTINCT {customer_name}) AS customer_count "
            f"FROM {customer_scope} "
            f"WHERE {_where_sql(where_parts)} "
            f"GROUP BY {channel_group} "
            "ORDER BY customer_count DESC"
        ),
        params,
    ).fetchall()
    total = sum(int(row.customer_count or 0) for row in rows)
    channels = [
        {
            "channel": row.channel,
            "count": int(row.customer_count or 0),
            "customers": int(row.customer_count or 0),
            "percentage": _percentage(int(row.customer_count or 0), total),
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
    customer_scope = _customer_scope_sql(campaign_tag)

    where_parts, params = _campaign_filters(
        campaign_tag=campaign_tag,
        industry=industry,
    )
    rows = db.execute(
        text(
            "SELECT COALESCE(NULLIF(c.role_coverage, ''), '0/4') AS role_coverage, "
            "COUNT(*) AS customer_count "
            f"FROM {customer_scope} "
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
    customer_scope = _customer_scope_sql(campaign_tag)

    where_parts, params = _campaign_filters(
        campaign_tag=campaign_tag,
        industry=industry,
    )
    rows = db.execute(
        text(
            "SELECT COALESCE(NULLIF(c.purchase_stage, ''), '未知阶段') AS stage, COUNT(*) AS count "
            f"FROM {customer_scope} "
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
    customer_scope = _customer_scope_sql(campaign_tag)

    customer_where, customer_params = _campaign_filters(
        campaign_tag=campaign_tag,
        industry=industry,
    )

    industry_rows = db.execute(
        text(
            "SELECT c.industry AS signal_name, COUNT(*) AS signal_count, '行业' AS signal_type "
            f"FROM {customer_scope} "
            f"WHERE {_where_sql(customer_where)} AND c.industry IS NOT NULL AND c.industry != '' "
            "GROUP BY c.industry ORDER BY signal_count DESC LIMIT 8"
        ),
        customer_params,
    ).fetchall()
    signals = [
        {"signal": row.signal_name, "count": int(row.signal_count or 0), "type": row.signal_type}
        for row in industry_rows
    ]
    return {"signals": signals, "help_key": "tag_signals"}


def _query_content_effect(
    db: Session,
    *,
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
) -> Dict[str, Any]:
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
            "i.content AS content, "
            "COUNT(*) AS touch_count, "
            "COUNT(DISTINCT i.customer_name) AS unique_customers, "
            "SUM(REGEXP_LIKE(CONCAT_WS(' ', i.behavior_type, i.content), "
            "'打开|浏览|触达|PAGE_VIEW', 'i')) AS opens, "
            "SUM(REGEXP_LIKE(CONCAT_WS(' ', i.behavior_type, i.content), "
            "'点击|下载|提交|咨询|报名|留资|click_', 'i')) AS clicks, "
            "SUM(CASE WHEN i.is_high_value = 1 THEN 1 ELSE 0 END) AS mql "
            "FROM dws_interaction_detail i "
            f"WHERE {_where_sql(where_parts)} AND i.content IS NOT NULL AND i.content != '' "
            "GROUP BY i.content "
            "ORDER BY unique_customers DESC, clicks DESC, touch_count DESC LIMIT 10"
        ),
        params,
    ).fetchall()

    data = [
        {
            "content": row.content,
            "type": "互动内容",
            "role": "按内容主题识别",
            "content_interest": row.content,
            "product_interest": "",
            "touch_count": int(row.touch_count or 0),
            "unique_customers": int(row.unique_customers or 0),
            "open_rate": round((int(row.opens or 0) / max(1, int(row.unique_customers or 0)) * 100), 2),
            "click_rate": round((int(row.clicks or 0) / max(1, int(row.unique_customers or 0)) * 100), 2),
            "mql": int(row.mql or 0),
            "sql": 0,
            "deal": 0,
        }
        for row in rows
    ]
    return {"data": data, "help_key": "content_effect"}


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
    return _query_content_effect(
        db,
        campaign_tag=campaign_tag,
        start_date=start_date,
        end_date=end_date,
        channel=channel,
        industry=industry,
    )


@router.get("/overview")
def get_campaign_overview(
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    include_content: bool = True,
    include_global_filter_options: bool = False,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Return all non-paginated campaign sections with two DB round trips."""
    started_at = time.perf_counter()
    customer_scope = _customer_scope_sql(campaign_tag)
    customer_name = _customer_name_sql(campaign_tag)

    base_where, base_params = _campaign_filters(
        campaign_tag=campaign_tag,
        industry=industry,
    )
    active_where, active_params = _campaign_filters(
        campaign_tag=campaign_tag,
        industry=industry,
        channel=channel,
        start_date=start_date,
        end_date=end_date,
        require_interaction_window=True,
    )
    metric_where, metric_params = _campaign_filters(
        campaign_tag=campaign_tag,
        industry=industry,
        channel=channel,
        start_date=start_date,
        end_date=end_date,
    )
    aggregate_params = {**base_params, **active_params, **metric_params}
    channel_group = channel_group_case(
        "c.last_interaction_channel",
        aggregate_params,
        prefix="overview_channel",
    )
    base_sql = _where_sql(base_where)
    active_sql = _where_sql(active_where)
    metric_sql = _where_sql(metric_where)
    global_option_sql = ""
    if include_global_filter_options:
        global_channel_group = channel_group_case(
            "i.channel",
            aggregate_params,
            prefix="global_filter_channel",
        )
        global_option_sql = (
            " UNION ALL "
            "SELECT 'campaign_option', c.campaign_tag, 0, 0, 0, 0, 0 "
            "FROM dws_customer_360 c "
            "WHERE c.campaign_tag IS NOT NULL AND c.campaign_tag != '' GROUP BY c.campaign_tag "
            "UNION ALL "
            "SELECT 'industry_option', c.industry, 0, 0, 0, 0, 0 "
            "FROM dws_customer_360 c "
            "WHERE c.industry IS NOT NULL AND c.industry != '' GROUP BY c.industry "
            "UNION ALL "
            f"SELECT 'channel_option', {global_channel_group}, 0, 0, 0, 0, 0 "
            "FROM dws_interaction_detail i "
            "WHERE i.channel IS NOT NULL AND TRIM(i.channel) != '' "
            f"GROUP BY {global_channel_group}"
        )

    query_started = time.perf_counter()
    aggregate_rows = db.execute(
        text(
            "SELECT 'kpi_total' AS section, '' AS label, "
            f"COUNT(DISTINCT {customer_name}) AS count_value, 0 AS active_value, "
            "0 AS deal_value, 0 AS unknown_value, 0 AS amount_value "
            f"FROM {customer_scope} "
            f"WHERE {base_sql} "
            "UNION ALL "
            f"SELECT 'kpi_active', '', COUNT(DISTINCT {customer_name}), 0, 0, 0, 0 "
            f"FROM {customer_scope} "
            f"WHERE {active_sql} "
            "UNION ALL "
            "SELECT 'kpi_metrics', '', "
            "COALESCE(SUM(COALESCE(NULLIF(c.active_opp_count, 0), c.funnel_opp_count, 0)), 0), "
            "0, COUNT(DISTINCT CASE WHEN COALESCE(c.won_amount, 0) > 0 "
            f"OR c.purchase_stage = '阶段6：完成采购，实现进入' THEN {customer_name} END), "
            "0, COALESCE(SUM(c.active_opp_amount), 0) "
            f"FROM {customer_scope} "
            f"WHERE {metric_sql} "
            "UNION ALL "
            "SELECT 'opportunity', COALESCE(NULLIF(c.forecast_type, ''), '未标注'), "
            "COUNT(*), "
            "SUM(CASE WHEN COALESCE(c.active_opp_count, 0) > 0 "
            "OR COALESCE(c.funnel_opp_count, 0) > 0 THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN COALESCE(c.won_amount, 0) > 0 "
            "OR c.purchase_stage = '阶段6：完成采购，实现进入' THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN c.purchase_stage IS NULL OR c.purchase_stage = '' THEN 1 ELSE 0 END), 0 "
            f"FROM {customer_scope} "
            f"WHERE {base_sql} "
            "GROUP BY COALESCE(NULLIF(c.forecast_type, ''), '未标注') "
            "UNION ALL "
            f"SELECT 'channel', {channel_group}, COUNT(DISTINCT {customer_name}), 0, 0, 0, 0 "
            f"FROM {customer_scope} "
            f"WHERE {base_sql} "
            f"GROUP BY {channel_group} "
            "UNION ALL "
            "SELECT 'stage', COALESCE(NULLIF(c.purchase_stage, ''), '未知阶段'), "
            f"COUNT(*), 0, 0, 0, 0 FROM {customer_scope} "
            f"WHERE {base_sql} "
            "GROUP BY COALESCE(NULLIF(c.purchase_stage, ''), '未知阶段') "
            "UNION ALL "
            "SELECT 'role', COALESCE(NULLIF(c.role_coverage, ''), '0/4'), "
            f"COUNT(*), 0, 0, 0, 0 FROM {customer_scope} "
            f"WHERE {base_sql} "
            "GROUP BY COALESCE(NULLIF(c.role_coverage, ''), '0/4') "
            "UNION ALL "
            "SELECT 'signal', c.industry, COUNT(*), 0, 0, 0, 0 "
            f"FROM {customer_scope} "
            f"WHERE {base_sql} AND c.industry IS NOT NULL AND c.industry != '' "
            "GROUP BY c.industry "
            "UNION ALL "
            "SELECT 'stage_option', c.purchase_stage, 0, 0, 0, 0, 0 "
            f"FROM {customer_scope} "
            f"WHERE {base_sql} AND c.purchase_stage IS NOT NULL AND c.purchase_stage != '' "
            "GROUP BY c.purchase_stage "
            "UNION ALL "
            "SELECT 'owner_option', c.owner_name, 0, 0, 0, 0, 0 "
            f"FROM {customer_scope} "
            f"WHERE {base_sql} AND c.owner_name IS NOT NULL AND c.owner_name != '' "
            f"GROUP BY c.owner_name{global_option_sql}"
        ),
        aggregate_params,
    ).fetchall()
    aggregates_ms = _elapsed_ms(query_started)

    total_customers = 0
    active_customers = 0
    opportunity_count = 0
    total_amount = 0.0
    deal_customers = 0
    categories: List[Dict[str, Any]] = []
    channel_items: List[Dict[str, Any]] = []
    stage_items: List[Dict[str, Any]] = []
    role_items: List[Dict[str, Any]] = []
    signal_items: List[Dict[str, Any]] = []
    stages_for_filter: List[str] = []
    owners_for_filter: List[str] = []
    campaigns_for_filter: List[str] = []
    industries_for_filter: List[str] = []
    channels_for_filter: List[str] = []

    for row in aggregate_rows:
        section = row.section
        count_value = int(row.count_value or 0)
        if section == "kpi_total":
            total_customers = count_value
        elif section == "kpi_active":
            active_customers = count_value
        elif section == "kpi_metrics":
            opportunity_count = count_value
            deal_customers = int(row.deal_value or 0)
            total_amount = float(row.amount_value or 0)
        elif section == "opportunity":
            categories.append({
                "forecast_type": row.label,
                "count": count_value,
                "active_count": int(row.active_value or 0),
                "deal_count": int(row.deal_value or 0),
                "unknown_count": int(row.unknown_value or 0),
            })
        elif section == "channel":
            channel_items.append({"channel": row.label, "count": count_value, "customers": count_value})
        elif section == "stage":
            stage_items.append({"stage": row.label, "count": count_value})
        elif section == "role":
            role_items.append({"role": row.label, "customer_count": count_value})
        elif section == "signal":
            signal_items.append({"signal": row.label, "count": count_value, "type": "行业"})
        elif section == "stage_option" and row.label:
            stages_for_filter.append(row.label)
        elif section == "owner_option" and row.label:
            owners_for_filter.append(row.label)
        elif section == "campaign_option" and row.label:
            campaigns_for_filter.append(row.label)
        elif section == "industry_option" and row.label:
            industries_for_filter.append(row.label)
        elif section == "channel_option" and row.label:
            channels_for_filter.append(row.label)

    categories.sort(key=lambda item: (-item["count"], item["forecast_type"]))
    for item in categories:
        item["percentage"] = _percentage(item["count"], total_customers)
    channel_items.sort(key=lambda item: (-item["count"], item["channel"]))
    for item in channel_items:
        item["percentage"] = _percentage(item["count"], total_customers)
    stage_items.sort(key=lambda item: (-item["count"], item["stage"]))
    for item in stage_items:
        item["percentage"] = _percentage(item["count"], total_customers)
    role_items.sort(key=lambda item: (-item["customer_count"], item["role"]))
    for item in role_items:
        item["coverage_percentage"] = _percentage(item["customer_count"], total_customers)
    signal_items.sort(key=lambda item: (-item["count"], item["signal"]))
    signal_items = signal_items[:8]

    kpis = {
        "total_customers": total_customers,
        "active_customers": active_customers,
        "opportunity_count": opportunity_count,
        "total_amount": total_amount,
        "deal_customers": deal_customers,
        "help_key": "campaign_kpis",
    }
    opportunity_distribution = {
        "categories": categories,
        "stages": categories,
        "total": total_customers,
        "help_key": "opportunity_distribution",
    }
    channel_distribution = {
        "channels": channel_items,
        "total": total_customers,
        "help_key": "channel_attribution",
    }

    content_ms = 0.0
    if include_content:
        query_started = time.perf_counter()
        content_effect = _query_content_effect(
            db,
            campaign_tag=campaign_tag,
            start_date=start_date,
            end_date=end_date,
            channel=channel,
            industry=industry,
        )
        content_ms = _elapsed_ms(query_started)
    else:
        content_effect = {"data": [], "help_key": "content_effect", "deferred": True}

    result = {
        "kpis": kpis,
        "opportunity_distribution": opportunity_distribution,
        "channel_distribution": channel_distribution,
        "stage_distribution": {
            "stages": stage_items,
            "total": total_customers,
            "help_key": "stage_distribution",
        },
        "role_coverage": {
            "roles": role_items,
            "total_customers": total_customers,
            "help_key": "role_coverage",
        },
        "tag_signals": {"signals": signal_items, "help_key": "tag_signals"},
        "content_effect": content_effect,
        "customer_filter_options": {
            "stages": sorted(set(stages_for_filter)),
            "owners": sorted(set(owners_for_filter)),
        },
    }
    if include_global_filter_options:
        available_global_channels = set(channels_for_filter)
        result["global_filter_options"] = {
            "campaigns": _campaign_options(campaigns_for_filter),
            "industries": sorted(set(industries_for_filter)),
            "channels": [
                channel
                for channel in CHANNEL_FILTER_ORDER
                if channel in available_global_channels
            ],
        }
    _log_timing(
        "overview",
        started_at,
        aggregates=aggregates_ms,
        content=content_ms,
    )
    return result


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
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=100, description="Customers per page"),
    include_filter_options: bool = Query(True, description="Include stage and owner options"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get customers for follow-up table."""
    started_at = time.perf_counter()
    customer_scope = _customer_scope_sql(campaign_tag)
    customer_name = _customer_name_sql(campaign_tag)
    campaign_label = _campaign_label_sql(campaign_tag)
    count_expression = (
        f"COUNT(DISTINCT {customer_name})"
        if _is_key_account_campaign(campaign_tag)
        else "COUNT(*)"
    )

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

    query_started = time.perf_counter()
    total = db.execute(
        text(f"SELECT {count_expression} FROM {customer_scope} WHERE {where_sql}"),
        params,
    ).scalar() or 0
    count_ms = _elapsed_ms(query_started)
    total_pages = max(1, (int(total) + page_size - 1) // page_size)
    current_page = min(page, total_pages)
    offset = (current_page - 1) * page_size

    query_started = time.perf_counter()
    rows = db.execute(
        text(
            f"SELECT c.id, {customer_name} AS customer_name, {campaign_label} AS campaign_tag, "
            "c.industry, c.region, c.attribute, "
            "c.purchase_stage AS stage, c.owner_name, c.intent_level, c.intent_score, "
            "c.role_coverage, c.last_interaction_time, c.last_interaction_channel, "
            "c.active_opp_amount, c.active_opp_count, c.interaction_count_total, "
            "c.product_categories, c.source_tables "
            f"FROM {customer_scope} "
            f"WHERE {where_sql} "
            f"ORDER BY (c.id IS NULL) ASC, c.intent_score DESC, c.active_opp_amount DESC, {customer_name} ASC "
            "LIMIT :page_size OFFSET :offset"
        ),
        {**params, "page_size": page_size, "offset": offset},
    ).fetchall()
    rows_ms = _elapsed_ms(query_started)

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

    filter_options = None
    options_ms = 0.0
    if include_filter_options:
        option_where, option_params = _campaign_filters(
            campaign_tag=campaign_tag,
            industry=industry,
        )
        option_sql = _where_sql(option_where)
        query_started = time.perf_counter()
        option_rows = db.execute(
            text(
                f"SELECT c.purchase_stage, c.owner_name FROM {customer_scope} "
                f"WHERE {option_sql} AND ((c.purchase_stage IS NOT NULL AND c.purchase_stage != '') "
                "OR (c.owner_name IS NOT NULL AND c.owner_name != ''))"
            ),
            option_params,
        ).fetchall()
        options_ms = _elapsed_ms(query_started)
        filter_options = {
            "stages": sorted({row.purchase_stage for row in option_rows if row.purchase_stage}),
            "owners": sorted({row.owner_name for row in option_rows if row.owner_name}),
        }

    result = {
        "grouped": grouped,
        "flat": customers,
        "total": total,
        "page": current_page,
        "page_size": page_size,
        "total_pages": total_pages,
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
        "help_key": "customer_followup",
    }
    if filter_options is not None:
        result["filter_options"] = filter_options
    _log_timing(
        "customers-by-stage",
        started_at,
        count=count_ms,
        rows=rows_ms,
        options=options_ms,
    )
    return result


def _get_bootstrap_defaults(db: Session) -> Dict[str, Optional[str]]:
    row = db.execute(text(
        "SELECT "
        "(SELECT campaign_tag FROM dws_customer_360 "
        " WHERE campaign_tag IS NOT NULL AND campaign_tag != '' "
        " ORDER BY campaign_tag ASC LIMIT 1) AS campaign_tag, "
        "(SELECT event_time FROM dws_interaction_detail "
        " WHERE event_time IS NOT NULL ORDER BY event_time ASC LIMIT 1) AS min_date, "
        "(SELECT event_time FROM dws_interaction_detail "
        " WHERE event_time IS NOT NULL ORDER BY event_time DESC LIMIT 1) AS max_date"
    )).one()
    return {
        "campaign_tag": row.campaign_tag,
        "min_date": _date_iso(row.min_date),
        "max_date": _date_iso(row.max_date),
    }


@router.get("/bootstrap")
def get_campaign_bootstrap(
    campaign_tag: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    channel: Optional[str] = None,
    industry: Optional[str] = None,
    page: int = Query(1, ge=1, description="Initial customer page"),
    page_size: int = Query(10, ge=1, le=100, description="Initial customer page size"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Load default filters, overview, and the first customer page in one request."""
    started_at = time.perf_counter()
    defaults = _get_bootstrap_defaults(db)
    applied_campaign = campaign_tag or defaults["campaign_tag"]
    applied_start = start_date or defaults["min_date"]
    applied_end = end_date or defaults["max_date"]

    customer_kwargs = {
        "campaign_tag": applied_campaign,
        "start_date": applied_start,
        "end_date": applied_end,
        "channel": channel,
        "industry": industry,
        "stage": None,
        "owner": None,
        "keyword": None,
        "page": page,
        "page_size": page_size,
        "include_filter_options": False,
    }

    if isinstance(db, Session):
        def with_session(loader):
            worker_db = get_session_factory()()
            try:
                return loader(worker_db)
            finally:
                worker_db.close()

        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="campaign-bootstrap") as executor:
            customer_future = executor.submit(
                with_session,
                lambda worker_db: get_customers_by_stage(db=worker_db, **customer_kwargs),
            )
            overview = get_campaign_overview(
                campaign_tag=applied_campaign,
                start_date=applied_start,
                end_date=applied_end,
                channel=channel,
                industry=industry,
                include_content=False,
                include_global_filter_options=True,
                db=db,
            )
            customers = customer_future.result()
    else:
        overview = get_campaign_overview(
            campaign_tag=applied_campaign,
            start_date=applied_start,
            end_date=applied_end,
            channel=channel,
            industry=industry,
            include_content=False,
            include_global_filter_options=True,
            db=db,
        )
        customers = get_customers_by_stage(db=db, **customer_kwargs)
    global_filter_options = overview.pop("global_filter_options", {})
    filter_options = {
        "campaigns": global_filter_options.get("campaigns", []),
        "industries": global_filter_options.get("industries", []),
        "channels": global_filter_options.get("channels", []),
        "min_date": defaults["min_date"],
        "max_date": defaults["max_date"],
    }
    result = {
        "filter_options": filter_options,
        "applied_filters": {
            "campaign_tag": applied_campaign,
            "start_date": applied_start,
            "end_date": applied_end,
            "channel": channel,
            "industry": industry,
        },
        "overview": overview,
        "customers": customers,
    }
    _log_timing("bootstrap", started_at)
    return result
