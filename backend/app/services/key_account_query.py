"""Shared query helpers for enriched key-account customer lists."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.channel_classification import add_customer_interaction_channel_filter
from app.services.region_filter import add_region_filter


KEY_ACCOUNT_TABLE = "ods_crm_key_account_output_list_day"
KEY_ACCOUNT_SOURCE_PROJECT = "企业彩光ICT"

_SORT_COLUMNS = {
    "customer_name": "ka.`重客名称`",
    "industry": "c.industry",
    "intent_score": "c.intent_score",
    "interaction_count_30d": "c.interaction_count_30d",
    "interaction_count_total": "c.interaction_count_total",
    "last_interaction_time": "c.last_interaction_time",
    "active_opp_amount": "c.active_opp_amount",
    "won_amount": "c.won_amount",
    "updated_at": "c.updated_at",
}


def _build_filters(
    *,
    keyword: Optional[str],
    industry: Optional[str],
    region: Optional[str],
    region_keyword: Optional[str],
    owner: Optional[str],
    owner_keyword: Optional[str],
    stage: Optional[str],
    intent_level: Optional[str],
    interaction_min: Optional[int],
    interaction_period: int,
    channel: Optional[str],
) -> Tuple[str, Dict[str, Any]]:
    where_parts = [
        f"ka.`time` = (SELECT MAX(`time`) FROM {KEY_ACCOUNT_TABLE})",
    ]
    params: Dict[str, Any] = {
        "key_account_source_project": KEY_ACCOUNT_SOURCE_PROJECT,
    }

    if keyword:
        where_parts.append("ka.`重客名称` LIKE :keyword")
        params["keyword"] = f"%{keyword}%"
    if industry:
        where_parts.append("c.industry = :industry")
        params["industry"] = industry
    add_region_filter(
        where_parts,
        params,
        column="c.region",
        region=region,
        region_keyword=region_keyword,
        prefix="key_account_region",
    )
    if owner:
        where_parts.append("c.owner_name = :owner")
        params["owner"] = owner
    elif owner_keyword:
        where_parts.append("c.owner_name LIKE :owner_keyword")
        params["owner_keyword"] = f"%{owner_keyword}%"
    if stage:
        where_parts.append("c.purchase_stage = :stage")
        params["stage"] = stage
    if intent_level:
        where_parts.append("c.intent_level = :intent_level")
        params["intent_level"] = intent_level
    if interaction_min is not None and interaction_min > 0:
        where_parts.append(
            """
            ka.`重客名称` IN (
                SELECT customer_name
                FROM dws_interaction_detail
                WHERE event_time >= DATE_SUB(NOW(), INTERVAL :period DAY)
                GROUP BY customer_name
                HAVING COUNT(*) >= :interaction_min
            )
            """
        )
        params["interaction_min"] = interaction_min
        params["period"] = interaction_period
    add_customer_interaction_channel_filter(
        where_parts,
        params,
        customer_name_column="ka.`重客名称`",
        channel=channel,
        prefix="key_account_channel",
    )

    return " AND ".join(where_parts), params


def _order_sql(sort: Optional[str]) -> str:
    sort_column = "c.intent_score"
    sort_order = "DESC"
    if sort:
        parts = sort.strip().split()
        sort_column = _SORT_COLUMNS.get(parts[0], sort_column)
        if len(parts) > 1 and parts[1].upper() == "ASC":
            sort_order = "ASC"
    return (
        f"(c.id IS NULL) ASC, {sort_column} {sort_order}, "
        "ka.`重客名称` ASC, ka.`重客编码` ASC"
    )


def _normalize_rows(rows) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["customer_name"] = item.pop("key_account_name")
        item["campaign_tag"] = "重客"
        items.append(item)
    return items


def count_key_accounts(
    db: Session,
    **filters: Any,
) -> int:
    where_sql, params = _build_filters(**filters)
    sql = text(
        f"""
        SELECT COUNT(*)
        FROM {KEY_ACCOUNT_TABLE} ka
        LEFT JOIN dws_customer_360 c
          ON c.customer_name = ka.`重客名称`
         AND c.campaign_tag = :key_account_source_project
        WHERE {where_sql}
        """
    )
    return db.execute(sql, params).scalar() or 0


def fetch_key_accounts(
    db: Session,
    *,
    page: Optional[int] = None,
    size: Optional[int] = None,
    limit: int = 20000,
    sort: Optional[str] = None,
    **filters: Any,
) -> List[Dict[str, Any]]:
    where_sql, params = _build_filters(**filters)
    order_sql = _order_sql(sort)

    if page is not None and size is not None:
        pagination_sql = "LIMIT :limit OFFSET :offset"
        params["limit"] = size
        params["offset"] = (page - 1) * size
    else:
        pagination_sql = "LIMIT :limit"
        params["limit"] = limit

    sql = text(
        f"""
        SELECT
            c.*,
            ka.`重客编码` AS key_account_code,
            ka.`重客名称` AS key_account_name
        FROM {KEY_ACCOUNT_TABLE} ka
        LEFT JOIN dws_customer_360 c
          ON c.customer_name = ka.`重客名称`
         AND c.campaign_tag = :key_account_source_project
        WHERE {where_sql}
        ORDER BY {order_sql}
        {pagination_sql}
        """
    )
    rows = db.execute(sql, params).mappings().all()
    return _normalize_rows(rows)
