"""
Query service for dws_interaction_detail.

Used by the interaction / timeline API endpoints.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def get_interactions(
    db: Session,
    *,
    customer_id: Optional[str] = None,
    contact_id: Optional[str] = None,
    channel: Optional[str] = None,
    source: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    keyword: Optional[str] = None,
    sort_by: str = "interaction_time",
    sort_order: str = "DESC",
    page: int = 1,
    page_size: int = 50,
) -> Dict[str, Any]:
    """Query dws_interaction_detail with flexible filters and pagination.

    Returns:
        Dict with keys: items (list of rows), total (count), page, page_size.
    """
    where_parts: List[str] = ["1=1"]
    params: Dict[str, Any] = {}

    if customer_id:
        where_parts.append("customer_id = :customer_id")
        params["customer_id"] = customer_id
    if contact_id:
        where_parts.append("contact_id = :contact_id")
        params["contact_id"] = contact_id
    if channel:
        where_parts.append("channel = :channel")
        params["channel"] = channel
    if source:
        where_parts.append("source = :source")
        params["source"] = source
    if start_time:
        where_parts.append("interaction_time >= :start_time")
        params["start_time"] = start_time
    if end_time:
        where_parts.append("interaction_time <= :end_time")
        params["end_time"] = end_time
    if keyword:
        where_parts.append("content LIKE :keyword")
        params["keyword"] = f"%{keyword}%"

    where_sql = " AND ".join(where_parts)

    # Count
    count_sql = text(f"SELECT COUNT(*) FROM dws_interaction_detail WHERE {where_sql}")
    total: int = db.execute(count_sql, params).scalar() or 0

    # Data
    allowed_sort = {"interaction_time", "channel", "source", "created_at"}
    if sort_by not in allowed_sort:
        sort_by = "interaction_time"
    order_dir = "ASC" if sort_order.upper() == "ASC" else "DESC"

    offset = (max(1, page) - 1) * page_size
    data_sql = text(
        f"SELECT * FROM dws_interaction_detail "
        f"WHERE {where_sql} "
        f"ORDER BY {sort_by} {order_dir} "
        f"LIMIT :limit OFFSET :offset"
    )
    params["limit"] = page_size
    params["offset"] = offset

    rows = db.execute(data_sql, params).mappings().all()

    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_interaction_summary(
    db: Session,
    customer_id: str,
) -> Dict[str, Any]:
    """Return a channel-level summary of interactions for a customer."""
    sql = text(
        "SELECT "
        "  channel, "
        "  COUNT(*) AS cnt, "
        "  MAX(interaction_time) AS last_time "
        "FROM dws_interaction_detail "
        "WHERE customer_id = :cid "
        "GROUP BY channel "
        "ORDER BY cnt DESC"
    )
    rows = db.execute(sql, {"cid": customer_id}).mappings().all()
    return {"customer_id": customer_id, "channels": [dict(r) for r in rows]}


def get_interaction_timeline(
    db: Session,
    customer_id: str,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Return the most recent interactions for a customer (for timeline view)."""
    sql = text(
        "SELECT * FROM dws_interaction_detail "
        "WHERE customer_id = :cid "
        "ORDER BY interaction_time DESC "
        "LIMIT :lim"
    )
    rows = db.execute(sql, {"cid": customer_id, "lim": limit}).mappings().all()
    return [dict(r) for r in rows]
