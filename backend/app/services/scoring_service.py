"""
Scoring & AI insight service.

Provides get_ai_insight() and get_priority_contact() for the customer-360 view.
Falls back to LLM generation when pre-computed data is unavailable.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Pre-computed reads
# ─────────────────────────────────────────────────────────────────────────────

def get_ai_insight(
    db: Session,
    customer_id: str,
) -> Dict[str, Any]:
    """Return the AI-generated insight for a customer.

    First reads the cached ai_insight column from dws_customer_360.
    If empty (or row missing), attempts a live LLM call and caches the result.

    Returns:
        Dict with keys: customer_id, insight (str), generated_at (str|None),
        source ("cached" | "live" | "unavailable").
    """
    # 1. Try cached value
    row = db.execute(
        text(
            "SELECT ai_insight, updated_at "
            "FROM dws_customer_360 "
            "WHERE customer_id = :cid"
        ),
        {"cid": customer_id},
    ).mappings().fetchone()

    if row and row.get("ai_insight"):
        return {
            "customer_id": customer_id,
            "insight": row["ai_insight"],
            "generated_at": str(row["updated_at"]) if row.get("updated_at") else None,
            "source": "cached",
        }

    # 2. Try live LLM generation
    live_insight = _generate_insight_via_llm(db, customer_id)
    if live_insight:
        # Cache the result
        db.execute(
            text(
                "UPDATE dws_customer_360 "
                "SET ai_insight = :insight, updated_at = NOW() "
                "WHERE customer_id = :cid"
            ),
            {"insight": live_insight, "cid": customer_id},
        )
        db.commit()
        return {
            "customer_id": customer_id,
            "insight": live_insight,
            "generated_at": None,
            "source": "live",
        }

    # 3. Fallback
    return {
        "customer_id": customer_id,
        "insight": "",
        "generated_at": None,
        "source": "unavailable",
    }


def get_priority_contact(
    db: Session,
    customer_id: str,
) -> Dict[str, Any]:
    """Recommend the best contact to reach out to within an account.

    Scoring heuristic (weighted):
      - Role:  decision_maker=30, champion=25, influencer=20, technical=15, other=5
      - Recent interaction recency:  30d→20, 90d→10, else 0
      - Engagement score (from dws_customer_360, normalised to 0–20)

    Returns:
        Dict with the top contact and reasoning, or empty if none found.
    """
    # Gather contacts + their interaction stats
    sql = text(
        "SELECT "
        "  cm.source_contact_id, cm.name, cm.email, cm.mobile, "
        "  cm.title, cm.role_category, cm.department, "
        "  c360.engagement_score, "
        "  c360.last_interaction_time "
        "FROM contact_mapping cm "
        "LEFT JOIN dws_customer_360 c360 "
        "  ON c360.customer_id = cm.customer_id "
        "WHERE cm.customer_id = :cid "
        "ORDER BY cm.name"
    )
    rows = db.execute(sql, {"cid": customer_id}).mappings().all()

    if not rows:
        return {"customer_id": customer_id, "contact": None, "reason": "No contacts found."}

    # Score each contact
    role_weights = {
        "decision_maker": 30,
        "champion": 25,
        "influencer": 20,
        "technical_evaluator": 15,
        "procurement": 10,
        "end_user": 5,
    }

    from datetime import datetime, timedelta

    now = datetime.now()
    scored: List[Dict[str, Any]] = []

    for r in rows:
        row = dict(r)
        # Role score
        role = (row.get("role_category") or "").lower()
        score = role_weights.get(role, 5)

        # Recency bonus
        last_time = row.get("last_interaction_time")
        if last_time:
            days_ago = (now - last_time).days
            if days_ago <= 30:
                score += 20
            elif days_ago <= 90:
                score += 10

        # Engagement bonus (cap at 20)
        eng = float(row.get("engagement_score") or 0)
        score += min(eng / 5, 20)

        row["priority_score"] = round(score, 1)
        scored.append(row)

    scored.sort(key=lambda x: x["priority_score"], reverse=True)
    top = scored[0]

    reasons: List[str] = []
    if top.get("role_category"):
        reasons.append(f"Role: {top['role_category']}")
    reasons.append(f"Priority score: {top['priority_score']}")

    return {
        "customer_id": customer_id,
        "contact": {
            "source_contact_id": top.get("source_contact_id"),
            "name": top.get("name"),
            "email": top.get("email"),
            "mobile": top.get("mobile"),
            "title": top.get("title"),
            "role_category": top.get("role_category"),
            "department": top.get("department"),
            "priority_score": top["priority_score"],
        },
        "reason": "; ".join(reasons),
        "all_contacts_scored": len(scored),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Private LLM helper
# ─────────────────────────────────────────────────────────────────────────────

def _generate_insight_via_llm(db: Session, customer_id: str) -> Optional[str]:
    """Call the configured LLM to generate a customer insight.

    Returns None if the LLM is not configured or the call fails.
    """
    if not settings.LLM_API_KEY or not settings.LLM_BASE_URL:
        logger.debug("LLM not configured; skipping live insight generation.")
        return None

    # Build context from interaction + opportunity data
    interactions = db.execute(
        text(
            "SELECT channel, interaction_type, interaction_time, content "
            "FROM dws_interaction_detail "
            "WHERE customer_id = :cid "
            "ORDER BY interaction_time DESC LIMIT 20"
        ),
        {"cid": customer_id},
    ).mappings().all()

    opps = db.execute(
        text(
            "SELECT opportunity_name, stage, amount, close_date "
            "FROM ods_crm_opportunity_day "
            "WHERE account_id = :cid "
            "ORDER BY close_date DESC LIMIT 5"
        ),
        {"cid": customer_id},
    ).mappings().all()

    if not interactions and not opps:
        return None

    # Build prompt
    context_lines: List[str] = []
    if interactions:
        context_lines.append("Recent interactions:")
        for ix in interactions:
            context_lines.append(
                f"  [{ix.get('interaction_time')}] {ix.get('channel')}/"
                f"{ix.get('interaction_type')}: {str(ix.get('content', ''))[:120]}"
            )
    if opps:
        context_lines.append("Opportunities:")
        for o in opps:
            context_lines.append(
                f"  {o.get('opportunity_name')} | {o.get('stage')} | "
                f"¥{o.get('amount', 0)} | close: {o.get('close_date')}"
            )

    prompt = (
        "You are a B2B sales analyst. Based on the following customer data, "
        "write a concise insight (2–4 sentences) summarising the customer's "
        "engagement level, buying signals, and recommended next action.\n\n"
        f"Customer ID: {customer_id}\n" + "\n".join(context_lines)
    )

    try:
        import httpx

        resp = httpx.post(
            f"{settings.LLM_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.LLM_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 300,
                "temperature": 0.4,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()

    except Exception as exc:
        logger.warning("LLM call failed for customer %s: %s", customer_id, exc)
        return None
