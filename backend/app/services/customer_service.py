"""
Customer 360 query service.

Provides get_customer_list() and get_filter_options() for the customer
list / search UI.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Customer list
# ─────────────────────────────────────────────────────────────────────────────

def get_customer_list(
    db: Session,
    *,
    keyword: Optional[str] = None,
    industry: Optional[str] = None,
    region: Optional[str] = None,
    min_engagement_score: Optional[float] = None,
    max_engagement_score: Optional[float] = None,
    min_opportunity_amount: Optional[float] = None,
    active_days_30d_min: Optional[int] = None,
    tags: Optional[List[str]] = None,
    sort_by: str = "engagement_score",
    sort_order: str = "DESC",
    page: int = 1,
    page_size: int = 50,
) -> Dict[str, Any]:
    """Query dws_customer_360 with flexible filters and pagination.

    Returns:
        Dict with items, total, page, page_size.
    """
    where_parts: List[str] = ["1=1"]
    params: Dict[str, Any] = {}

    if keyword:
        where_parts.append(
            "(customer_name LIKE :kw OR company_name LIKE :kw OR customer_id LIKE :kw)"
        )
        params["kw"] = f"%{keyword}%"
    if industry:
        where_parts.append("industry = :industry")
        params["industry"] = industry
    if region:
        where_parts.append("region = :region")
        params["region"] = region
    if min_engagement_score is not None:
        where_parts.append("engagement_score >= :min_eng")
        params["min_eng"] = min_engagement_score
    if max_engagement_score is not None:
        where_parts.append("engagement_score <= :max_eng")
        params["max_eng"] = max_engagement_score
    if min_opportunity_amount is not None:
        where_parts.append("opportunity_amount >= :min_opp")
        params["min_opp"] = min_opportunity_amount
    if active_days_30d_min is not None:
        where_parts.append("active_days_30d >= :min_active")
        params["min_active"] = active_days_30d_min
    if tags:
        # JSON_CONTAINS for each tag; OR-combined
        tag_clauses = []
        for i, tag in enumerate(tags):
            key = f"tag{i}"
            tag_clauses.append(f"JSON_CONTAINS(tags, :{key})")
            params[key] = f'"{tag}"'
        where_parts.append(f"({' OR '.join(tag_clauses)})")

    where_sql = " AND ".join(where_parts)

    # Count
    count_sql = text(f"SELECT COUNT(*) FROM dws_customer_360 WHERE {where_sql}")
    total: int = db.execute(count_sql, params).scalar() or 0

    # Data
    allowed_sort = {
        "engagement_score", "customer_name", "company_name",
        "total_interactions", "last_interaction_time", "opportunity_amount",
        "active_days_30d", "updated_at",
    }
    if sort_by not in allowed_sort:
        sort_by = "engagement_score"
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
    items: List[Dict[str, Any]] = []
    for r in rows:
        row = dict(r)
        # Ensure tags is a list (may come back as JSON string)
        if isinstance(row.get("tags"), str):
            import json
            try:
                row["tags"] = json.loads(row["tags"])
            except (json.JSONDecodeError, TypeError):
                row["tags"] = []
        items.append(row)

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Filter options (facets for the search UI)
# ─────────────────────────────────────────────────────────────────────────────

def get_filter_options(db: Session) -> Dict[str, Any]:
    """Return distinct values for all filterable facets.

    Used to populate dropdown / multi-select controls in the frontend.

    Returns:
        Dict with keys: industries, regions, tags, engagement_score_range,
        opportunity_amount_range.
    """
    industries = _distinct_values(db, "dws_customer_360", "industry")
    regions = _distinct_values(db, "dws_customer_360", "region")

    # Tags – extract from JSON array column
    tags_sql = text(
        "SELECT DISTINCT jt.tag "
        "FROM dws_customer_360, "
        "     JSON_TABLE(tags, '$[*]' COLUMNS (tag VARCHAR(128) PATH '$')) AS jt "
        "WHERE jt.tag IS NOT NULL AND jt.tag != '' "
        "ORDER BY jt.tag"
    )
    try:
        tag_rows = db.execute(tags_sql).fetchall()
        tags = [r[0] for r in tag_rows]
    except Exception:
        tags = []

    # Numeric ranges
    ranges_sql = text(
        "SELECT "
        "  MIN(engagement_score) AS min_eng, MAX(engagement_score) AS max_eng, "
        "  MIN(opportunity_amount) AS min_opp, MAX(opportunity_amount) AS max_opp "
        "FROM dws_customer_360"
    )
    range_row = db.execute(ranges_sql).mappings().fetchone() or {}

    return {
        "industries": industries,
        "regions": regions,
        "tags": tags,
        "engagement_score_range": {
            "min": float(range_row.get("min_eng") or 0),
            "max": float(range_row.get("max_eng") or 0),
        },
        "opportunity_amount_range": {
            "min": float(range_row.get("min_opp") or 0),
            "max": float(range_row.get("max_opp") or 0),
        },
    }


# ── Helpers ─────────────────────────────────────────────────────────────────

def _distinct_values(db: Session, table: str, column: str) -> List[str]:
    """Return sorted distinct non-null values for a column."""
    sql = text(
        f"SELECT DISTINCT {column} FROM {table} "
        f"WHERE {column} IS NOT NULL AND {column} != '' "
        f"ORDER BY {column}"
    )
    rows = db.execute(sql).fetchall()
    return [r[0] for r in rows]
