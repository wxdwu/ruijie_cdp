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

    return dict(row)


# ─────────────────────────────────────────────────────────────────────────────
# b. GET /api/customers/{id}/contacts - Get customer contacts list
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{id}/contacts")
def get_customer_contacts(
    id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get customer contacts list from dws_contact_mapping."""
    # First get customer_name from dws_customer_360
    customer_name = _get_customer_name(db, id)

    # Then query dws_contact_mapping by customer_name
    rows = db.execute(
        text(
            "SELECT * FROM dws_contact_mapping "
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

    # Contact insights
    contact_count = customer.get("contact_count", 0)
    mobile_count = customer.get("mobile_count", 0)
    contact_insights = [
        f"联系人覆盖率：共{contact_count}位联系人，其中{mobile_count}位有手机号",
    ]

    if mobile_count >= contact_count and contact_count > 0:
        contact_insights.append("联系人手机号覆盖率100%，信息完整度高")

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

    return {
        "business_conclusion": business_conclusion,
        "contact_insights": contact_insights,
        "evidence": evidence,
    }


# ─────────────────────────────────────────────────────────────────────────────
# f. GET /api/customers/{id}/priority-contact - Priority contact recommendation
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{id}/priority-contact")
def get_customer_priority_contact(
    id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get priority contact recommendation for the customer."""
    # Get customer_name from dws_customer_360
    customer_name = _get_customer_name(db, id)

    # Get all contacts from dws_contact_mapping
    rows = db.execute(
        text(
            "SELECT id, customer_name, contact_name, mobile, email, department, "
            "position, purchase_role, role_category "
            "FROM dws_contact_mapping "
            "WHERE customer_name = :cname "
            "ORDER BY contact_name"
        ),
        {"cname": customer_name},
    ).mappings().all()

    candidates = [dict(r) for r in rows]

    if not candidates:
        return {
            "recommended": {},
            "candidates": [],
        }

    # Score contacts based on role
    role_weights = {
        "决策者": 100,
        "决策层": 90,
        "关键人": 80,
        "技术把关": 70,
        "使用者": 50,
        "影响者": 40,
    }

    scored_contacts = []
    for contact in candidates:
        score = 0
        role = contact.get("role_category", "") or contact.get("purchase_role", "")
        score = role_weights.get(role, 30)

        # Bonus for having mobile
        if contact.get("mobile"):
            score += 20
        # Bonus for having email
        if contact.get("email"):
            score += 10

        contact["priority_score"] = score
        scored_contacts.append(contact)

    # Sort by score descending
    scored_contacts.sort(key=lambda x: x["priority_score"], reverse=True)

    # Recommended is the top one
    recommended = scored_contacts[0]

    return {
        "recommended": recommended,
        "candidates": scored_contacts,
    }
