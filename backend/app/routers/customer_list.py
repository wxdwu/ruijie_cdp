"""
Customer list API router.

Provides endpoints for listing customers with filters, getting filter options,
and exporting customer data to Excel.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.export_service import export_customers_excel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/customers", tags=["customers"])


# ─────────────────────────────────────────────────────────────────────────────
# Customer list endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.get("")
def list_customers(
    db: Session = Depends(get_db),
    keyword: Optional[str] = Query(None, description="Search by customer_name"),
    industry: Optional[str] = Query(None, description="Filter by industry"),
    owner: Optional[str] = Query(None, description="Filter by owner_name"),
    stage: Optional[str] = Query(None, description="Filter by purchase_stage"),
    intent_level: Optional[str] = Query(None, description="Filter by intent_level"),
    interaction_min: Optional[int] = Query(None, description="Minimum interaction count (30d)"),
    channel: Optional[str] = Query(None, description="Filter by last_interaction_channel"),
    sort: Optional[str] = Query(None, description="Sort field and direction, e.g. 'intent_score desc'"),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Page size (max 100)"),
) -> Dict[str, Any]:
    """List customers with filters and pagination."""
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
        where_parts.append("interaction_count_30d >= :interaction_min")
        params["interaction_min"] = interaction_min
    if channel:
        where_parts.append("last_interaction_channel = :channel")
        params["channel"] = channel

    where_sql = " AND ".join(where_parts)

    # Count total
    count_sql = text(f"SELECT COUNT(*) FROM dws_customer_360 WHERE {where_sql}")
    total: int = db.execute(count_sql, params).scalar() or 0

    # Sorting
    sort_by = "intent_score"
    sort_order = "DESC"
    if sort:
        parts = sort.strip().split()
        allowed_sort = {
            "customer_name", "industry", "intent_score", "interaction_count_30d",
            "interaction_count_total", "last_interaction_time", "active_opp_amount",
            "won_amount", "updated_at",
        }
        if parts[0] in allowed_sort:
            sort_by = parts[0]
        if len(parts) > 1 and parts[1].upper() == "ASC":
            sort_order = "ASC"

    # Pagination
    offset = (page - 1) * size
    data_sql = text(
        f"SELECT * FROM dws_customer_360 "
        f"WHERE {where_sql} "
        f"ORDER BY {sort_by} {sort_order} "
        f"LIMIT :limit OFFSET :offset"
    )
    params["limit"] = size
    params["offset"] = offset

    rows = db.execute(data_sql, params).mappings().all()
    items = [dict(r) for r in rows]

    filters_applied = {
        "keyword": keyword,
        "industry": industry,
        "owner": owner,
        "stage": stage,
        "intent_level": intent_level,
        "interaction_min": interaction_min,
        "channel": channel,
        "sort": sort,
    }

    return {
        "total": total,
        "items": items,
        "filters_applied": filters_applied,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Filter options endpoint
# ─────────────────────────────────────────────────────────────────────────────

def _distinct_values(db: Session, column: str) -> List[str]:
    """Return sorted distinct non-null values for a column."""
    sql = text(
        f"SELECT DISTINCT {column} FROM dws_customer_360 "
        f"WHERE {column} IS NOT NULL AND {column} != '' "
        f"ORDER BY {column}"
    )
    rows = db.execute(sql).fetchall()
    return [r[0] for r in rows]


@router.get("/filter-options")
def get_filter_options(db: Session = Depends(get_db)) -> Dict[str, List[str]]:
    """Return distinct values for all filterable facets from dws_customer_360."""
    return {
        "industries": _distinct_values(db, "industry"),
        "owners": _distinct_values(db, "owner_name"),
        "stages": _distinct_values(db, "purchase_stage"),
        "intent_levels": _distinct_values(db, "intent_level"),
        "channels": _distinct_values(db, "last_interaction_channel"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Export endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/export")
def export_customers(
    db: Session = Depends(get_db),
    keyword: Optional[str] = Query(None, description="Search by customer_name"),
    industry: Optional[str] = Query(None, description="Filter by industry"),
    owner: Optional[str] = Query(None, description="Filter by owner_name"),
    stage: Optional[str] = Query(None, description="Filter by purchase_stage"),
    intent_level: Optional[str] = Query(None, description="Filter by intent_level"),
    interaction_min: Optional[int] = Query(None, description="Minimum interaction count (30d)"),
    channel: Optional[str] = Query(None, description="Filter by last_interaction_channel"),
    sort: Optional[str] = Query(None, description="Sort field and direction, e.g. 'intent_score desc'"),
) -> Response:
    """Export filtered customer list as Excel file."""
    # Parse sort
    sort_by = "intent_score"
    sort_order = "DESC"
    if sort:
        parts = sort.strip().split()
        allowed_sort = {
            "customer_name", "industry", "intent_score", "interaction_count_30d",
            "interaction_count_total", "last_interaction_time", "active_opp_amount",
            "won_amount", "updated_at",
        }
        if parts[0] in allowed_sort:
            sort_by = parts[0]
        if len(parts) > 1 and parts[1].upper() == "ASC":
            sort_order = "ASC"

    excel_bytes = export_customers_excel(
        db,
        keyword=keyword,
        industry=industry,
        region=owner,  # mapping owner to region for export service (uses different param names)
        sort_by=sort_by,
        sort_order=sort_order,
    )

    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=customers_export.xlsx",
        },
    )
