"""
Customer 360 query service - refactored for actual dws_customer_360 schema.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

ALLOWED_SORT = {
    "customer_name", "industry", "intent_score", "interaction_count_30d",
    "interaction_count_total", "last_interaction_time", "active_opp_amount",
    "won_amount", "updated_at",
}

def get_customer_list(
    db: Session,
    *,
    keyword: Optional[str] = None,
    industry: Optional[str] = None,
    owner: Optional[str] = None,
    stage: Optional[str] = None,
    intent_level: Optional[str] = None,
    interaction_min: Optional[int] = None,
    channel: Optional[str] = None,
    sort_by: str = "intent_score",
    sort_order: str = "DESC",
    page: int = 1,
    page_size: int = 50,
) -> Dict[str, Any]:
    where_parts: List[str] = ["1=1"]
    params: Dict[str, Any] = {}

    if keyword:
        where_parts.append("customer_name LIKE :keyword")
        params["keyword"] = f"%{keyword}%"
    if industry:
        where_parts.append("industry = :industry")
        params["industry"] = industry
    if owner:
        where_parts.append("owner_name = :owner")
        params["owner"] = owner
    if stage:
        where_parts.append("purchase_stage = :stage")
        params["stage"] = stage
    if intent_level:
        where_parts.append("intent_level = :intent_level")
        params["intent_level"] = intent_level
    if interaction_min is not None:
        where_parts.append("interaction_count_30d >= :imin")
        params["imin"] = interaction_min
    if channel:
        where_parts.append("last_interaction_channel = :channel")
        params["channel"] = channel

    where_sql = " AND ".join(where_parts)

    # Count
    count_sql = text(f"SELECT COUNT(*) FROM dws_customer_360 WHERE {where_sql}")
    total = db.execute(count_sql, params).scalar() or 0

    # Sort validation
    if sort_by not in ALLOWED_SORT:
        sort_by = "intent_score"
    order_dir = "ASC" if sort_order.upper() == "ASC" else "DESC"

    offset = (max(1, page) - 1) * page_size
    data_sql = text(
        f"SELECT * FROM dws_customer_360 "
        f"WHERE {where_sql} "
        f"ORDER BY {sort_by} {order_dir} "
        f"LIMIT :limit OFFSET :offset"
    )
    params["limit"] = page_size
    params["offset"] = offset

    rows = db.execute(data_sql, params).mappings().all()
    items = [dict(r) for r in rows]

    return {"items": items, "total": total, "page": page, "page_size": page_size}


def get_filter_options(db: Session) -> Dict[str, Any]:
    industries = _distinct_values(db, "industry")
    owners = _distinct_values(db, "owner_name")
    stages = _distinct_values(db, "purchase_stage")
    intent_levels = _distinct_values(db, "intent_level")
    channels = _distinct_values(db, "last_interaction_channel")

    return {
        "industries": industries,
        "owners": owners,
        "stages": stages,
        "intent_levels": intent_levels,
        "channels": channels,
    }


def _distinct_values(db: Session, column: str) -> List[str]:
    sql = text(
        f"SELECT DISTINCT {column} FROM dws_customer_360 "
        f"WHERE {column} IS NOT NULL AND {column} != '' ORDER BY {column}"
    )
    rows = db.execute(sql).fetchall()
    return [r[0] for r in rows]