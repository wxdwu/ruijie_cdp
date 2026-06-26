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
    customer_row = db.execute(
        text(
            "SELECT customer_name, purchase_stage, intent_level "
            "FROM dws_customer_360 WHERE id = :cid"
        ),
        {"cid": id},
    ).mappings().fetchone()

    if not customer_row:
        raise HTTPException(status_code=404, detail=f"Customer {id} not found")

    customer_name = customer_row["customer_name"]

    # Query dws_contact_360 which already has interaction counts aggregated
    rows = db.execute(
        text(
            "SELECT c.id, c.customer_id, c.contact_name, c.mobile, c.email, "
            "       c.department, c.position, c.purchase_role, c.role_category, "
            "       c.interaction_count, c.interaction_count_30d, "
            "       c.last_interaction_time, c.top_content_types, "
            "       c.product_interests, c.activity_level, c.intent_level, "
            "       c.lead_stage, c.source_tables, c.linkflow_contact_id, "
            "       COALESCE(c.lead_stage, :customer_stage) AS purchase_stage, "
            "       :customer_stage AS customer_purchase_stage, "
            "       COALESCE(c.intent_level, :customer_intent_level) AS display_intent_level, "
            "       :customer_intent_level AS customer_intent_level, "
            "       CAST(COALESCE(hv.high_value_count, 0) AS SIGNED) AS high_value_count, "
            "       pc.channel AS preferred_channel "
            "FROM dws_contact_360 c "
            "LEFT JOIN ( "
            "    SELECT contact_name, mobile, "
            "           SUM(CASE WHEN is_high_value = 1 THEN 1 ELSE 0 END) AS high_value_count "
            "    FROM dws_interaction_detail "
            "    WHERE customer_name = :cname "
            "    GROUP BY contact_name, mobile "
            ") hv ON hv.contact_name <=> c.contact_name "
            "     AND hv.mobile <=> c.mobile "
            "LEFT JOIN ( "
            "    SELECT contact_name, mobile, channel "
            "    FROM ( "
            "        SELECT contact_name, mobile, channel, "
            "               ROW_NUMBER() OVER ( "
            "                   PARTITION BY contact_name, mobile "
            "                   ORDER BY COUNT(*) DESC, MAX(event_time) DESC "
            "               ) AS rn "
            "        FROM dws_interaction_detail "
            "        WHERE customer_name = :cname "
            "          AND channel IS NOT NULL AND channel != '' "
            "        GROUP BY contact_name, mobile, channel "
            "    ) preferred_ranked "
            "    WHERE rn = 1 "
            ") pc ON pc.contact_name <=> c.contact_name "
            "     AND pc.mobile <=> c.mobile "
            "WHERE c.customer_id = :cid "
            "ORDER BY c.interaction_count DESC, c.contact_name"
        ),
        {
            "cid": id,
            "cname": customer_name,
            "customer_stage": customer_row.get("purchase_stage"),
            "customer_intent_level": customer_row.get("intent_level"),
        },
    ).mappings().all()

    # If dws_contact_360 is empty (not built yet), fall back to dws_contact_mapping
    if not rows:
        rows = db.execute(
            text(
                "SELECT cm.id, cm.contact_name, cm.mobile, cm.email, "
                "       cm.department, cm.position, cm.purchase_role, "
                "       cm.role_category, cm.source_table, "
                "       JSON_ARRAY(cm.source_table) AS source_tables, "
                "       cm.linkflow_contact_id, "
                "       0 AS interaction_count, 0 AS interaction_count_30d, "
                "       NULL AS last_interaction_time, NULL AS top_content_types, "
                "       NULL AS product_interests, NULL AS activity_level, "
                "       NULL AS intent_level, NULL AS lead_stage, "
                "       :customer_stage AS purchase_stage, "
                "       :customer_stage AS customer_purchase_stage, "
                "       :customer_intent_level AS display_intent_level, "
                "       :customer_intent_level AS customer_intent_level, "
                "       CAST(COALESCE(hv.high_value_count, 0) AS SIGNED) AS high_value_count, "
                "       pc.channel AS preferred_channel "
                "FROM dws_contact_mapping cm "
                "LEFT JOIN ( "
                "    SELECT contact_name, mobile, "
                "           SUM(CASE WHEN is_high_value = 1 THEN 1 ELSE 0 END) AS high_value_count "
                "    FROM dws_interaction_detail "
                "    WHERE customer_name = :cname "
                "    GROUP BY contact_name, mobile "
                ") hv ON hv.contact_name <=> cm.contact_name "
                "     AND hv.mobile <=> cm.mobile "
                "LEFT JOIN ( "
                "    SELECT contact_name, mobile, channel "
                "    FROM ( "
                "        SELECT contact_name, mobile, channel, "
                "               ROW_NUMBER() OVER ( "
                "                   PARTITION BY contact_name, mobile "
                "                   ORDER BY COUNT(*) DESC, MAX(event_time) DESC "
                "               ) AS rn "
                "        FROM dws_interaction_detail "
                "        WHERE customer_name = :cname "
                "          AND channel IS NOT NULL AND channel != '' "
                "        GROUP BY contact_name, mobile, channel "
                "    ) preferred_ranked "
                "    WHERE rn = 1 "
                ") pc ON pc.contact_name <=> cm.contact_name "
                "     AND pc.mobile <=> cm.mobile "
                "WHERE cm.customer_name = :cname "
                "ORDER BY cm.contact_name"
            ),
            {
                "cname": customer_name,
                "customer_stage": customer_row.get("purchase_stage"),
                "customer_intent_level": customer_row.get("intent_level"),
            },
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

    # Get recent interaction count for the business conclusion.
    interaction_count = db.execute(
        text(
            "SELECT COUNT(*) FROM dws_interaction_detail "
            "WHERE customer_name = :cname "
            "  AND event_time >= DATE_SUB(NOW(), INTERVAL 3 MONTH)"
        ),
        {"cname": customer_name},
    ).scalar() or 0

    # Get funnel opportunity count from dws_customer_360.
    opp_count = int(customer.get("funnel_opp_count") or 0)

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
        business_conclusion.append(f"客户近3个月互动活跃（{interaction_count}次），购买信号强烈")
    elif interaction_count > 0:
        business_conclusion.append(f"客户近3个月有{interaction_count}次互动记录，保持跟进")
    else:
        business_conclusion.append("客户近3个月暂无互动记录，建议主动触达")

    # Opportunity insight
    if opp_count > 0:
        business_conclusion.append(f"客户现有{opp_count}个漏斗内商机，需重点维护")

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
