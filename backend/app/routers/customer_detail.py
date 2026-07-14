"""
客户 360 详情路由。

整合客户画像、联系人、互动时间线、CRM 商机、规则洞察和优先联系人推荐。
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
# 公共辅助方法：将客户 ID 转换为跨业务表通用的客户名称
# ─────────────────────────────────────────────────────────────────────────────

def _get_customer_name(db: Session, customer_id: str) -> str:
    """按客户 ID 获取客户名称；客户不存在时统一返回 404。"""
    row = db.execute(
        text("SELECT customer_name FROM dws_customer_360 WHERE id = :cid"),
        {"cid": customer_id},
    ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")

    return row[0]


# ─────────────────────────────────────────────────────────────────────────────
# 客户概览：返回基础画像并实时补充互动、拜访指标
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{id}")
def get_customer_detail(
    id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """按 ID 获取客户 360 详情。"""
    row = db.execute(
        text("SELECT * FROM dws_customer_360 WHERE id = :cid"),
        {"cid": id},
    ).mappings().fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Customer {id} not found")

    result = dict(row)
    # 从互动明细实时重算近 30 天互动数，避免依赖画像表中的历史聚合值。
    # 例如今天是 7 月 14 日，则只统计 6 月 14 日至今该客户的互动记录。
    interaction_count_30d = db.execute(
        text(
            "SELECT COUNT(*) FROM dws_interaction_detail "
            "WHERE customer_name = :cname "
            "  AND event_time >= DATE_SUB(NOW(), INTERVAL 30 DAY)"
        ),
        {"cname": result.get("customer_name")},
    ).scalar() or 0
    result["interaction_count_30d"] = int(interaction_count_30d)

    # 汇总该客户所有联系人的拜访情况：MAX 取最近一次拜访时间，
    # MIN 取最短未拜访天数。例如两名联系人分别 3 天、10 天未拜访，返回 3 天。
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
# 联系人列表：融合联系人画像、互动价值和偏好渠道
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{id}/contacts")
def get_customer_contacts(
    id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """返回客户联系人列表及其互动、意向和触达偏好。"""
    # 客户级采购阶段和意向等级用于补齐联系人画像中的缺失值。
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

    # 优先读取联系人 360 聚合结果，并从互动明细补充两类衍生指标：
    # 1. hv 子查询按“姓名 + 手机号”统计 is_high_value=1 的互动次数；
    # 2. pc 子查询按渠道计数，ROW_NUMBER 将每位联系人最常用的渠道排在第 1 名，
    #    次数相同时以最近使用时间决胜。例如微信 5 次、邮件 2 次，则偏好渠道为微信。
    # SQL 使用 MySQL 的 <=> 空值安全比较，使双方手机号都为空时仍可正确关联。
    rows = db.execute(
        text(
            "SELECT c.id, c.customer_id, c.contact_name, c.mobile, c.email, "
            "       c.department, c.position, c.purchase_role, c.role_category, "
            "       c.interaction_count, c.interaction_count_30d, "
            "       c.last_interaction_time, c.top_content_types, "
            "       c.product_interests, c.activity_level, c.intent_level, "
            "       c.lead_stage, c.source_tables, c.linkflow_contact_id, "
            # 联系人自身阶段/意向优先；为空时继承客户级结果，避免页面出现无意义空值。
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

    # 联系人 360 尚未产出时回退到映射表，保证详情页仍能展示基础联系人。
    # 映射表没有联系人级互动聚合字段，因此相关计数暂置 0，但仍通过相同子查询
    # 补充高价值互动数和偏好渠道，让回退结果尽可能接近联系人 360 的返回结构。
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
# 互动时间线：按发生时间倒序展示客户触点
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{id}/interactions")
def get_customer_interactions(
    id: str,
    limit: int = Query(50, ge=1, le=500, description="最多返回的互动条数"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """返回客户最近的互动明细，数量由 limit 控制。"""
    # 互动表以客户名称关联，因此先由客户 ID 获取标准客户名称。
    customer_name = _get_customer_name(db, id)

    # 最新互动优先，供详情页按时间线展示近期触达行为；例如 limit=18 时
    # 只返回最近 18 条官网、邮件、活动等触点，不代表客户累计互动总数。
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
# 商机列表：展示客户在 CRM 中的历史及当前商机
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{id}/opportunities")
def get_customer_opportunities(
    id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """按创建时间倒序返回客户的 CRM 商机。"""
    # 商机表以客户名称关联，因此先由客户 ID 获取标准客户名称。
    customer_name = _get_customer_name(db, id)

    # 返回全部商机并按创建时间倒序，便于同时查看当前转化进程和历史机会；
    # 与客户画像中的 funnel_opp_count 不同，这里返回的是可逐条展示的原始商机。
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
# 客户洞察：基于画像、互动和商机规则生成跟进建议
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{id}/ai-insight")
def get_customer_ai_insight(
    id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """生成规则型客户洞察，并推荐优先跟进联系人。"""
    from app.services.contact_recommend import recommend_priority_contacts

    # 读取完整客户画像，作为洞察规则和证据字段的数据基础。
    customer_name = _get_customer_name(db, id)
    customer_row = db.execute(
        text("SELECT * FROM dws_customer_360 WHERE id = :cid"),
        {"cid": id},
    ).mappings().fetchone()

    if not customer_row:
        raise HTTPException(status_code=404, detail=f"Customer {id} not found")

    customer = dict(customer_row)

    # 统计近 3 个月互动量，用于判断客户活跃度和触达建议。
    interaction_count = db.execute(
        text(
            "SELECT COUNT(*) FROM dws_interaction_detail "
            "WHERE customer_name = :cname "
            "  AND event_time >= DATE_SUB(NOW(), INTERVAL 3 MONTH)"
        ),
        {"cname": customer_name},
    ).scalar() or 0

    # 使用客户 360 中已聚合的漏斗内商机数判断商机维护优先级。
    opp_count = int(customer.get("funnel_opp_count") or 0)

    # 分别从意向、互动活跃度和在途商机三个维度形成业务结论。
    # 例如“高意向 + 近 3 个月互动 12 次 + 2 个在途商机”会生成三条跟进提示。
    business_conclusion = []

    # 意向等级决定客户应重点跟进、持续培育还是先做市场教育。
    intent_level = customer.get("intent_level", "")
    if intent_level == "高":
        business_conclusion.append("客户处于高意向阶段，建议重点跟进")
    elif intent_level == "中":
        business_conclusion.append("客户处于中意向阶段，需要持续培育")
    elif intent_level == "低":
        business_conclusion.append("客户意向度较低，建议先进行市场教育")

    # 互动频次反映近期购买信号强弱及是否需要主动唤醒。
    if interaction_count > 10:
        business_conclusion.append(f"客户近3个月互动活跃（{interaction_count}次），购买信号强烈")
    elif interaction_count > 0:
        business_conclusion.append(f"客户近3个月有{interaction_count}次互动记录，保持跟进")
    else:
        business_conclusion.append("客户近3个月暂无互动记录，建议主动触达")

    # 存在漏斗内商机时提示销售持续维护。
    if opp_count > 0:
        business_conclusion.append(f"客户现有{opp_count}个漏斗内商机，需重点维护")

    contact_count = customer.get("contact_count", 0)
    mobile_count = customer.get("mobile_count", 0)

    # 同步返回结论所依据的关键指标，便于前端解释洞察来源。
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

    # 从该客户联系人中选出最值得优先跟进的前三人。
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
