"""
Campaign board API router.

Provides endpoints for campaign dashboard KPIs, funnel distribution,
channel distribution, role coverage, content effect, and customer follow-up.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/campaign", tags=["campaign"])


# ─────────────────────────────────────────────────────────────────────────────
# KPIs Endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/kpis")
def get_campaign_kpis(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Get 5 key performance indicators for campaign dashboard."""

    # Total customers
    total_customers = db.execute(text(
        "SELECT COUNT(*) FROM dws_customer_360"
    )).scalar() or 0

    # Total interactions
    total_interactions = db.execute(text(
        "SELECT COUNT(*) FROM dws_interaction_detail"
    )).scalar() or 0

    # Total opportunities
    total_opportunities = db.execute(text(
        "SELECT COUNT(*) FROM dws_customer_360 WHERE active_opp_amount > 0"
    )).scalar() or 0

    # 成交金额：purchase_stage = '阶段6：完成采购，实现进入' 视为已成交
    won_amount = db.execute(text(
        "SELECT COALESCE(SUM(active_opp_amount), 0) FROM dws_customer_360 "
        "WHERE purchase_stage = '阶段6：完成采购，实现进入'"
    )).scalar() or 0

    # 转化率 = 成交客户数 / 有机会客户数
    won_count = db.execute(text(
        "SELECT COUNT(*) FROM dws_customer_360 "
        "WHERE purchase_stage = '阶段6：完成采购，实现进入'"
    )).scalar() or 0

    conversion_rate = round((won_count / total_opportunities * 100), 2) if total_opportunities > 0 else 0

    return {
        "total_customers": total_customers,
        "total_interactions": total_interactions,
        "total_opportunities": total_opportunities,
        "won_amount": float(won_amount),
        "conversion_rate": conversion_rate
    }


# ─────────────────────────────────────────────────────────────────────────────
# Funnel Distribution
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/funnel-distribution")
def get_funnel_distribution(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Get funnel stage distribution from dws_customer_360."""

    result = db.execute(text(
        "SELECT purchase_stage as stage, COUNT(*) as count "
        "FROM dws_customer_360 "
        "WHERE purchase_stage IS NOT NULL AND purchase_stage != '' "
        "GROUP BY purchase_stage "
        "ORDER BY CASE purchase_stage "
        "    WHEN 'Awareness' THEN 1 "
        "    WHEN 'Consideration' THEN 2 "
        "    WHEN 'Decision' THEN 3 "
        "    WHEN 'Proposal' THEN 4 "
        "    WHEN 'Negotiation' THEN 5 "
        "    WHEN 'Closed Won' THEN 6 "
        "    WHEN 'Closed Lost' THEN 7 "
        "    ELSE 8 "
        "END"
    )).fetchall()

    stages = [
        {"stage": row.stage, "count": row.count}
        for row in result
    ]

    total = sum(s["count"] for s in stages)
    for stage in stages:
        stage["percentage"] = round((stage["count"] / total * 100), 2) if total > 0 else 0

    return {
        "stages": stages,
        "total": total
    }


# ─────────────────────────────────────────────────────────────────────────────
# Channel Distribution
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/channel-distribution")
def get_channel_distribution(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Get channel distribution from dws_interaction_detail."""

    result = db.execute(text(
        "SELECT channel, COUNT(*) as count "
        "FROM dws_interaction_detail "
        "WHERE channel IS NOT NULL AND channel != '' "
        "GROUP BY channel "
        "ORDER BY count DESC"
    )).fetchall()

    channels = [
        {"channel": row.channel, "count": row.count}
        for row in result
    ]

    total = sum(c["count"] for c in channels)
    for channel in channels:
        channel["percentage"] = round((channel["count"] / total * 100), 2) if total > 0 else 0

    return {
        "channels": channels,
        "total": total
    }


# ─────────────────────────────────────────────────────────────────────────────
# Role Coverage
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/role-coverage")
def get_role_coverage(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Get role coverage statistics."""

    # Count customers by owner/role
    result = db.execute(text(
        "SELECT owner_name as role, COUNT(*) as customer_count, "
        "SUM(interaction_count_30d) as total_interactions, "
        "SUM(active_opp_amount) as total_opportunity_value "
        "FROM dws_customer_360 "
        "WHERE owner_name IS NOT NULL AND owner_name != '' "
        "GROUP BY owner_name "
        "ORDER BY customer_count DESC"
    )).fetchall()

    roles = [
        {
            "role": row.role,
            "customer_count": row.customer_count,
            "total_interactions": row.total_interactions or 0,
            "total_opportunity_value": float(row.total_opportunity_value or 0)
        }
        for row in result
    ]

    total_customers = sum(r["customer_count"] for r in roles)
    for role in roles:
        role["coverage_percentage"] = round((role["customer_count"] / total_customers * 100), 2) if total_customers > 0 else 0

    return {
        "roles": roles,
        "total_customers": total_customers
    }


# ─────────────────────────────────────────────────────────────────────────────
# Content Effect
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/content-effect")
def get_content_effect(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Get content interaction effect table."""

    # 按 behavior_type 分类统计各渠道的内容互动效果，而不是不存在的interaction_type
    # 分类规则：
    #   opens     -> 打开邮件（zhique 邮件打开行为）
    #   downloads -> 下载资料（zhique）+ click_download（linkflow）
    #   clicks    -> 其余所有行为（除"打开邮件"外均视为点击互动）
    
    # TODO: 后续根据业务精细化分类？？
    
    result = db.execute(text(
        "SELECT "
        "    channel, "
        "    COUNT(*) as total_interactions, "
        "    COUNT(DISTINCT customer_name) as unique_customers, "
        "    COUNT(CASE WHEN behavior_type != '打开邮件' THEN 1 END) as clicks, "
        "    COUNT(CASE WHEN behavior_type = '打开邮件' THEN 1 END) as opens, "
        "    COUNT(CASE WHEN behavior_type IN ('下载资料', 'click_download') THEN 1 END) as downloads "
        "FROM dws_interaction_detail "
        "WHERE channel IS NOT NULL AND channel != '' "
        "GROUP BY channel "
        "ORDER BY total_interactions DESC"
    )).fetchall()

    content_data = [
        {
            "channel": row.channel,
            "total_interactions": row.total_interactions,
            "unique_customers": row.unique_customers,
            "clicks": row.clicks or 0,
            "opens": row.opens or 0,
            "downloads": row.downloads or 0,
            "click_rate": round((row.clicks / row.total_interactions * 100), 2) if row.total_interactions > 0 else 0
        }
        for row in result
    ]

    return {
        "data": content_data
    }


# ─────────────────────────────────────────────────────────────────────────────
# Customers by Stage
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/customers-by-stage")
def get_customers_by_stage(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Get customers by stage for funnel visualization."""

    result = db.execute(text(
        "SELECT "
        "    purchase_stage as stage, "
        "    customer_name, "
        "    intent_level, "
        "    intent_score, "
        "    active_opp_amount "
        "FROM dws_customer_360 "
        "WHERE purchase_stage IS NOT NULL AND purchase_stage != '' "
        "ORDER BY "
        "    CASE purchase_stage "
        "        WHEN '问题识别' THEN 1 "
        "        WHEN '解决方案探索' THEN 2 "
        "        WHEN '需求构建' THEN 3 "
        "        WHEN '已完成' THEN 4 "
        "        ELSE 5 "
        "    END, "
        "    intent_score DESC"
    )).fetchall()

    customers = [
        {
            "stage": row.stage,
            "customer_name": row.customer_name,
            "intent_level": row.intent_level,
            "intent_score": float(row.intent_score or 0),
            "active_opp_amount": float(row.active_opp_amount or 0)
        }
        for row in result
    ]

    # Group by stage
    grouped = {}
    for customer in customers:
        stage = customer["stage"]
        if stage not in grouped:
            grouped[stage] = []
        grouped[stage].append(customer)

    return {
        "grouped": grouped,
        "flat": customers
    }
