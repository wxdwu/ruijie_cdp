"""
Customer detail API router.

Provides endpoints for customer 360 detail view:
- Customer detail from dws_customer_360
- Contact list from dws_contact_mapping
- Interaction timeline from dws_interaction_detail
- CRM opportunities from ods_crm_opportunity_day
- AI insight (rule-based)
- Priority contact recommendation
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/customers", tags=["customers"])


# ─────────────────────────────────────────────────────────────────────────────
# Helper: Get customer by ID and return customer_name
# ─────────────────────────────────────────────────────────────────────────────

def _get_customer_name(db: Session, customer_id: str) -> str:
    """Get customer_name from dws_customer_360 by id."""
    row = db.execute(
        text("SELECT customer_name FROM dws_customer_360 WHERE id = :cid"),
        {"cid": customer_id},
    ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")

    return row[0]


# ─────────────────────────────────────────────────────────────────────────────
# a. GET /api/customers/{id} - Get customer detail
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{id}")
def get_customer_detail(
    id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get customer detail from dws_customer_360 by id."""
    row = db.execute(
        text("SELECT * FROM dws_customer_360 WHERE id = :cid"),
        {"cid": id},
    ).mappings().fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Customer {id} not found")

    result = dict(row)
    visit_row = db.execute(
        text(
            "SELECT MAX(last_visit_time) AS last_visit_time, "
            "       MIN(not_visit_days) AS no_visit_days "
            "FROM ods_crm_contact_day "
            "WHERE customer_name = :cname"
        ),
        {"cname": result.get("customer_name")},
    ).mappings().fetchone()

    if visit_row:
        result["last_visit_time"] = visit_row.get("last_visit_time")
        result["no_visit_days"] = visit_row.get("no_visit_days")
    else:
        result["last_visit_time"] = None
        result["no_visit_days"] = None

    return result


# ─────────────────────────────────────────────────────────────────────────────
# b. GET /api/customers/{id}/contacts - Get customer contacts list
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{id}/contacts")
def get_customer_contacts(
    id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get customer contacts list from dws_contact_360 with interaction data."""
    # Get customer_name
    customer_name = _get_customer_name(db, id)

    # Query dws_contact_360 which already has interaction counts aggregated
    rows = db.execute(
        text(
            "SELECT contact_name, mobile, email, department, position, "
            "       purchase_role, role_category, interaction_count, "
            "       interaction_count_30d, last_interaction_time, "
            "       top_content_types, product_interests, activity_level, "
            "       intent_level, linkflow_contact_id "
            "FROM dws_contact_360 "
            "WHERE customer_id = :cid "
            "ORDER BY interaction_count DESC"
        ),
        {"cid": id},
    ).mappings().all()

    # If dws_contact_360 is empty (not built yet), fall back to dws_contact_mapping
    if not rows:
        rows = db.execute(
            text(
                "SELECT contact_name, mobile, email, department, position, "
                "       purchase_role, role_category, source_table, "
                "       linkflow_contact_id "
                "FROM dws_contact_mapping "
                "WHERE customer_name = :cname "
                "ORDER BY contact_name"
            ),
            {"cname": customer_name},
        ).mappings().all()

    return {
        "customer_id": id,
        "customer_name": customer_name,
        "contacts": [dict(r) for r in rows],
        "total": len(rows),
    }


# ─────────────────────────────────────────────────────────────────────────────
# c. GET /api/customers/{id}/interactions - Get interaction timeline
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{id}/interactions")
def get_customer_interactions(
    id: str,
    limit: int = Query(50, ge=1, le=500, description="Maximum number of interactions to return"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get customer interaction timeline from dws_interaction_detail."""
    # Get customer_name from dws_customer_360
    customer_name = _get_customer_name(db, id)

    # Query dws_interaction_detail by customer_name, ordered by event_time DESC
    rows = db.execute(
        text(
            "SELECT * FROM dws_interaction_detail "
            "WHERE customer_name = :cname "
            "ORDER BY event_time DESC "
            "LIMIT :lim"
        ),
        {"cname": customer_name, "lim": limit},
    ).mappings().all()

    return {
        "customer_id": id,
        "customer_name": customer_name,
        "interactions": [dict(r) for r in rows],
        "total": len(rows),
    }


# ─────────────────────────────────────────────────────────────────────────────
# d. GET /api/customers/{id}/opportunities - Get CRM opportunities
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{id}/opportunities")
def get_customer_opportunities(
    id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get CRM opportunities from ods_crm_opportunity_day."""
    # Get customer_name from dws_customer_360
    customer_name = _get_customer_name(db, id)

    # Query ods_crm_opportunity_day by customer_name
    rows = db.execute(
        text(
            "SELECT * FROM ods_crm_opportunity_day "
            "WHERE customer_name = :cname "
            "ORDER BY create_date DESC"
        ),
        {"cname": customer_name},
    ).mappings().all()

    return {
        "customer_id": id,
        "customer_name": customer_name,
        "opportunities": [dict(r) for r in rows],
        "total": len(rows),
    }


# ─────────────────────────────────────────────────────────────────────────────
# e. GET /api/customers/{id}/ai-insight - AI insight (rule-based)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{id}/ai-insight")
def get_customer_ai_insight(
    id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get AI-generated insight for the customer (rule-based)."""
    from app.services.contact_recommend import recommend_priority_contacts

    # Get customer data
    customer_name = _get_customer_name(db, id)
    customer_row = db.execute(
        text("SELECT * FROM dws_customer_360 WHERE id = :cid"),
        {"cid": id},
    ).mappings().fetchone()

    if not customer_row:
        raise HTTPException(status_code=404, detail=f"Customer {id} not found")

    customer = dict(customer_row)

    # Get interaction count
    interaction_count = db.execute(
        text(
            "SELECT COUNT(*) FROM dws_interaction_detail WHERE customer_name = :cname"
        ),
        {"cname": customer_name},
    ).scalar() or 0

    # Get opportunity count
    opp_count = db.execute(
        text(
            "SELECT COUNT(*) FROM ods_crm_opportunity_day WHERE customer_name = :cname AND is_active = 1"
        ),
        {"cname": customer_name},
    ).scalar() or 0

    # Build rule-based business conclusions
    business_conclusion = []

    # Intent level insight
    intent_level = customer.get("intent_level", "")
    if intent_level == "高":
        business_conclusion.append("客户处于高意向阶段，建议重点跟进")
    elif intent_level == "中":
        business_conclusion.append("客户处于中意向阶段，需要持续培育")
    elif intent_level == "低":
        business_conclusion.append("客户意向度较低，建议先进行市场教育")

    # Interaction insight
    if interaction_count > 10:
        business_conclusion.append(f"客户近期互动活跃（{interaction_count}次），购买信号强烈")
    elif interaction_count > 0:
        business_conclusion.append(f"客户有{interaction_count}次互动记录，保持跟进")
    else:
        business_conclusion.append("客户暂无互动记录，建议主动触达")

    # Opportunity insight
    if opp_count > 0:
        business_conclusion.append(f"客户现有{opp_count}个活跃商机，需重点维护")

    contact_count = customer.get("contact_count", 0)
    mobile_count = customer.get("mobile_count", 0)

    # Evidence data
    evidence = {
        "intent_score": customer.get("intent_score", 0),
        "intent_level": intent_level,
        "interaction_count": interaction_count,
        "opportunity_count": opp_count,
        "contact_count": contact_count,
        "mobile_count": mobile_count,
        "last_interaction_time": str(customer.get("last_interaction_time", "")),
        "last_interaction_channel": customer.get("last_interaction_channel", ""),
    }

    priority_result = recommend_priority_contacts(
        db=db,
        customer_id=id,
        customer_name=customer_name,
        top_n=3,
    )

    return {
        "business_conclusion": business_conclusion,
        "evidence": evidence,
        "recommendation": priority_result.get("recommendation"),
        "recommendations": priority_result.get("recommendations", []),
        "total_candidates": priority_result.get("total_candidates", 0),
        "source": priority_result.get("source", "rule"),
    }
