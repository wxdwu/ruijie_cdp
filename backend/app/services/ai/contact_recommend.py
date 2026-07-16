"""
AI 优先联系人推荐服务

综合考虑角色权重、互动活跃度、最近互动时间、信息完整度等因素，
生成规则版优先推进对象、推进原因、触达方式和推荐话术。

设计原则：
- 本阶段不调用大模型，避免详情页等待外部模型响应
- 规则评分作为排序依据，规则模板生成推进建议
- 保留单对象和数组两种响应形态，兼容已有前端消费
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# 配置常量
# ─────────────────────────────────────────────────────────────────────────────

# 角色权重映射（采购决策影响力）
ROLE_WEIGHTS: Dict[str, int] = {
    "决策者": 100,
    "决策层": 95,
    "关键人": 80,
    "拍板者": 90,
    "技术把关": 70,
    "技术评估者": 65,
    "使用者": 50,
    "影响者": 40,
    "采购": 45,
    "其他": 20,
}

# 意向等级加分
INTENT_BONUS: Dict[str, int] = {
    "高": 25,
    "中": 15,
    "低": 5,
}

# 活跃度加分
ACTIVITY_BONUS: Dict[str, int] = {
    "高": 25,
    "medium": 25,
    "中": 15,
    "低": 5,
    "none": 0,
}

# 各维度权重（规则评分使用）
SCORE_WEIGHTS = {
    "role": 0.35,             # 角色权重
    "interaction": 0.25,      # 互动活跃度
    "recency": 0.20,          # 最近互动
    "completeness": 0.10,     # 信息完整度
    "intent": 0.10,           # 意向等级
}

# 固定推荐数量
MIN_RECOMMENDATIONS = 1
# AI 分析的候选人数上限（选规则分最高的 N 个发送给 AI）
AI_CANDIDATE_LIMIT = 8





# ─────────────────────────────────────────────────────────────────────────────
# 数据获取
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_contacts(db: Session, customer_name: str, customer_id: str) -> List[Dict[str, Any]]:
    """
    获取客户的所有联系人数据，优先从 dws_contact_360 获取（含互动统计），
    如果为空则回退到 dws_contact_mapping。

    Returns:
        联系人列表，每个联系人是一个字典
    """
    # 优先查询 dws_contact_360（已聚合互动数据）
    rows = db.execute(
        text(
            "SELECT contact_name, mobile, email, department, position, "
            "       purchase_role, role_category, interaction_count, "
            "       interaction_count_30d, last_interaction_time, "
            "       top_content_types, product_interests, activity_level, "
            "       intent_level "
            "FROM dws_contact_360 "
            "WHERE customer_id = :cid "
            "ORDER BY interaction_count DESC"
        ),
        {"cid": customer_id},
    ).mappings().all()

    if rows:
        return [dict(r) for r in rows]

    # 回退到 dws_contact_mapping
    rows = db.execute(
        text(
            "SELECT contact_name, mobile, email, department, position, "
            "       purchase_role, role_category "
            "FROM dws_contact_mapping "
            "WHERE customer_name = :cname "
            "ORDER BY contact_name"
        ),
        {"cname": customer_name},
    ).mappings().all()

    return [dict(r) for r in rows]


def _fetch_customer_context(db: Session, customer_id: str) -> Dict[str, Any]:
    """
    获取客户上下文信息，用于 AI 分析时的背景参考。

    Returns:
        包含行业、阶段、意向等信息的字典
    """
    row = db.execute(
        text(
            "SELECT customer_name, industry, campaign_tag, purchase_stage, "
            "       forecast_type, highest_stage_opp, intent_level, "
            "       intent_score, interaction_count_30d, active_opp_count, "
            "       active_opp_amount, owner_name "
            "FROM dws_customer_360 "
            "WHERE id = :cid"
        ),
        {"cid": customer_id},
    ).mappings().fetchone()

    if row:
        return dict(row)
    return {}


def _fetch_high_value_count(
    db: Session,
    customer_name: str,
    contact: Dict[str, Any],
) -> int:
    """获取联系人高价值行为数；缺少可匹配信息时返回 0。"""
    params: Dict[str, Any] = {"cname": customer_name}
    filters: List[str] = ["customer_name = :cname", "is_high_value = 1"]

    contact_name = contact.get("contact_name")
    mobile = contact.get("mobile")
    if contact_name:
        filters.append("contact_name = :contact_name")
        params["contact_name"] = contact_name
    elif mobile:
        filters.append("mobile = :mobile")
        params["mobile"] = mobile
    else:
        return 0

    return int(db.execute(
        text(
            "SELECT COUNT(*) FROM dws_interaction_detail "
            f"WHERE {' AND '.join(filters)}"
        ),
        params,
    ).scalar() or 0)


# ─────────────────────────────────────────────────────────────────────────────
# 规则评分
# ─────────────────────────────────────────────────────────────────────────────

def _compute_rule_scores(contacts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    对联系人列表进行多维规则评分。

    评分维度：
    1. 角色权重 —— 采购决策链中的影响力
    2. 互动活跃度 —— interaction_count_30d 标准化
    3. 最近互动 —— 30天/90天/更早衰减
    4. 信息完整度 —— 手机+邮箱+部门+职位
    5. 意向等级 —— intent_level 映射

    Returns:
        每个联系人增加 rule_score 和 detail 字段的列表
    """
    now = datetime.now()
    scored: List[Dict[str, Any]] = []

    # 先统计互动最大值，用于归一化
    i30d_values = [
        c.get("interaction_count_30d") or 0 for c in contacts
    ]
    max_i30d = max(i30d_values) if i30d_values else 1

    for contact in contacts:
        detail: Dict[str, float] = {}

        # 1. 角色评分 (0-100)
        role = contact.get("role_category", "") or contact.get("purchase_role", "")
        role_score = ROLE_WEIGHTS.get(role, 20)
        detail["role"] = round(role_score * SCORE_WEIGHTS["role"], 1)

        # 2. 互动活跃度 (0-100，归一化)
        i30d = contact.get("interaction_count_30d") or 0
        interaction_score = min(100, (i30d / max(max_i30d, 1)) * 100)
        detail["interaction"] = round(interaction_score * SCORE_WEIGHTS["interaction"], 1)

        # 3. 最近互动分数 (0-100)
        last_time = contact.get("last_interaction_time")
        recency_score = 0
        if last_time:
            if isinstance(last_time, str):
                try:
                    last_time = datetime.fromisoformat(str(last_time))
                except (ValueError, TypeError):
                    last_time = None
        if last_time and isinstance(last_time, datetime):
            days_ago = (now - last_time).days
            if days_ago <= 7:
                recency_score = 100
            elif days_ago <= 30:
                recency_score = 80
            elif days_ago <= 90:
                recency_score = 50
            elif days_ago <= 180:
                recency_score = 25
            else:
                recency_score = 10
        detail["recency"] = round(recency_score * SCORE_WEIGHTS["recency"], 1)

        # 4. 信息完整度 (0-100)
        completeness = 0
        if contact.get("mobile"):
            completeness += 35
        if contact.get("email"):
            completeness += 25
        if contact.get("department"):
            completeness += 20
        if contact.get("position"):
            completeness += 20
        detail["completeness"] = round(completeness * SCORE_WEIGHTS["completeness"], 1)

        # 5. 意向等级加分 (0-100)
        intent = contact.get("intent_level", "")
        intent_score = INTENT_BONUS.get(intent, 10)
        detail["intent"] = round(intent_score * 4 * SCORE_WEIGHTS["intent"], 1)
        # intent_score 本身最高 25，x4 映射到 0-100

        # 6. 活跃度加分 (0-100)
        activity = contact.get("activity_level", "")
        activity_score = ACTIVITY_BONUS.get(activity, 5)
        # 活跃度作为附加分，合并到互动维度

        # 计算总分
        total_score = round(
            sum(detail.values()) + activity_score * 0.05, 1
        )

        contact["rule_score"] = total_score
        contact["rule_detail"] = detail
        scored.append(contact)

    # 按规则分降序排列
    scored.sort(key=lambda x: x["rule_score"], reverse=True)
    return scored


# ─────────────────────────────────────────────────────────────────────────────
# AI 推荐生成
# ─────────────────────────────────────────────────────────────────────────────

def _build_ai_prompt(
    contacts: List[Dict[str, Any]],
    customer_context: Dict[str, Any],
) -> str:
    """构建发送给 AI 分析的结构化提示词。"""
    # 获取客户上下文
    cname = customer_context.get("customer_name", "未知客户")
    industry = customer_context.get("industry", "未知")
    stage = customer_context.get("purchase_stage", "未知")
    intent_level = customer_context.get("intent_level", "未知")

    # 构建联系人数据
    contact_lines: List[str] = []
    for i, c in enumerate(contacts, 1):
        name = c.get("contact_name") or "未知"
        role = c.get("role_category") or c.get("purchase_role") or "未知"
        dept = c.get("department") or "未知"
        position = c.get("position") or "未知"
        i30d = c.get("interaction_count_30d") or 0
        i_total = c.get("interaction_count") or 0
        last_time = str(c.get("last_interaction_time", "无"))[:10] if c.get(
            "last_interaction_time") else "无"
        activity = c.get("activity_level") or "未知"
        intent = c.get("intent_level") or "未知"
        rule_score = c.get("rule_score", 0)
        product = c.get("product_interests") or "无"

        contact_lines.append(
            f"  {i}. {name} | 角色: {role} | 部门: {dept} | 职位: {position} | "
            f"30天互动: {i30d}次 | 总互动: {i_total}次 | 最近互动: {last_time} | "
            f"活跃度: {activity} | 意向: {intent} | 兴趣产品: {product} | "
            f"规则评分: {rule_score}"
        )

    prompt = f"""
你是一位 B2B 销售顾问，需要为客户推荐最值得优先联系的联系人。

## 客户背景
- 客户名称: {cname}
- 行业: {industry}
- 采购阶段: {stage}
- 整体意向等级: {intent_level}

## 联系人候选列表（已按规则评分排序）
{chr(10).join(contact_lines)}

## 推荐要求
请从以上候选人中推荐最多 5 位最值得优先联系的联系人（若不足 5 位则全部推荐），综合考虑以下因素：
1. **决策影响力**: 角色在采购决策链中的位置（决策层 > 关键人 > 技术把关 > 使用者）
2. **互动活跃度**: 近期互动频率越高，越值得优先联系
3. **最近互动时间**: 最近有互动的优先于长时间未联系的
4. **信息完整度**: 有手机、邮箱的联系人更易触达
5. **意向信号**: 意向等级高、对产品有兴趣的联系人更可能转化
6. **阶段匹配**: 联系人角色是否与当前采购阶段匹配（如早期阶段优先联系技术把关，后期优先联系决策者）

## 输出格式
请输出一个严格的 JSON 数组，每个元素包含：
- "contact_name": 联系人姓名（必须与输入完全一致）
- "relevance_score": 相关性评分（0-100 整数，越高越推荐）
- "reason": 推荐理由（30-80字，具体说明为什么推荐此人，避免空泛）

只输出 JSON 数组，不包含 markdown 标记或其他文本。
示例: [{{"contact_name":"张三","relevance_score":95,"reason":"..."}}, ...]
"""
    return prompt


def _parse_ai_response(
    ai_response: str,
    contacts: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], str]:
    """
    解析 AI 返回的 JSON 结果，并与原始联系人数据合并。

    Returns:
        (推荐列表, 数据处理标记: "ai" | "rule_fallback")
    """
    try:
        # 清理可能的 markdown 标记
        cleaned = ai_response.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            cleaned = "\n".join(lines)

        recommendations = json.loads(cleaned)

        if not isinstance(recommendations, list):
            raise ValueError("AI 返回的不是数组格式")

        # 构建姓名字典用于快速查找
        contact_map: Dict[str, Dict[str, Any]] = {}
        for c in contacts:
            name = c.get("contact_name", "")
            if name:
                contact_map[name] = c

        # 合并 AI 评分和理由到联系人数据
        merged: List[Dict[str, Any]] = []
        for rec in recommendations:
            rec_name = rec.get("contact_name", "")
            base = contact_map.get(rec_name)
            if base:
                merged.append({
                    **base,
                    "ai_relevance_score": rec.get("relevance_score", base.get("rule_score", 50)),
                    "reason": rec.get("reason", f"综合评估推荐，角色: {base.get('role_category', '未知')}"),
                })

        # 如果没有匹配到任何联系人，可能是 AI 返回的姓名格式有差异
        if not merged:
            logger.warning("AI 返回的姓名与数据不匹配，回退规则评分")
            return _build_rule_fallback(contacts), "rule_fallback"

        # 按 AI 相关性分数降序排列
        merged.sort(key=lambda x: x.get("ai_relevance_score", 0), reverse=True)

        # 确保至少返回 3 个推荐
        if len(merged) < MIN_RECOMMENDATIONS:
            # 从剩余的规则评分候选中补足
            recommended_names = {m.get("contact_name") for m in merged}
            remaining = [
                _build_rule_recommendation(c)
                for c in contacts
                if c.get("contact_name") not in recommended_names
            ]
            remaining.sort(
                key=lambda x: x.get("ai_relevance_score", x.get("rule_score", 0)),
                reverse=True,
            )
            while len(merged) < MIN_RECOMMENDATIONS and remaining:
                merged.append(remaining.pop(0))

        return merged, "ai"

    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning("AI 响应解析失败 (%s)，回退规则评分", e)
        return _build_rule_fallback(contacts), "rule_fallback"


def _build_rule_recommendation(contact: Dict[str, Any]) -> Dict[str, Any]:
    """为单个联系人构建规则推荐数据。"""
    role = contact.get("role_category") or contact.get("purchase_role") or "未知"
    i30d = contact.get("interaction_count_30d") or 0
    last_time = contact.get("last_interaction_time")
    last_str = str(last_time)[:10] if last_time else ""
    intent = contact.get("intent_level", "")

    # 构建规则理由
    reason_parts: List[str] = []
    if role and role in ("决策者", "决策层", "拍板者"):
        reason_parts.append(f"担任{role}角色，决策影响力强")
    elif role and role in ("关键人", "技术把关", "技术评估者"):
        reason_parts.append(f"作为{role}，在采购中发挥重要作用")
    elif role:
        reason_parts.append(f"角色为{role}")

    if i30d >= 5:
        reason_parts.append(f"近30天互动{i30d}次，高度活跃")
    elif i30d >= 2:
        reason_parts.append(f"近30天互动{i30d}次，较为活跃")
    elif i30d >= 1:
        reason_parts.append("近期有过互动")

    if last_str:
        reason_parts.append(f"最近互动: {last_str}")

    if intent == "高":
        reason_parts.append("意向等级高")
    elif intent == "中":
        reason_parts.append("意向等级中等")

    if contact.get("mobile") and contact.get("email"):
        reason_parts.append("联系方式完整，易于触达")

    reason = "；".join(reason_parts) if reason_parts else "综合评分较高，建议优先联系"

    return {
        **contact,
        "ai_relevance_score": contact.get("rule_score", 50),
        "reason": reason,
    }


def _first_meaningful_value(*values: Any, default: str) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            value = "、".join(str(v) for v in value if v)
        elif isinstance(value, dict):
            value = "、".join(str(v) for v in value.values() if v)
        else:
            value = str(value)
        value = value.strip().strip('"').strip("'")
        if value and value not in {"未知", "无", "-", "null", "None", "[]", "{}"}:
            return value
    return default


def _format_interest(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "、".join(str(v).strip() for v in value if str(v).strip())
    if isinstance(value, dict):
        return "、".join(str(v).strip() for v in value.values() if str(v).strip())

    raw = str(value).strip()
    if not raw or raw in {"未知", "无", "-", "[]", "{}"}:
        return ""
    try:
        parsed = json.loads(raw)
        if parsed != raw:
            return _format_interest(parsed)
    except (json.JSONDecodeError, TypeError):
        pass
    return raw.strip("|").replace("|", "、")


def _stage_text(customer_context: Dict[str, Any]) -> str:
    return _first_meaningful_value(
        customer_context.get("purchase_stage"),
        customer_context.get("forecast_type"),
        customer_context.get("highest_stage_opp"),
        default="当前阶段",
    )


def _stage_dialogue_text(stage: str) -> str:
    """将 CRM 阶段原文转为适合销售话术的表达。"""
    stage = stage or ""
    if "阶段1" in stage or stage == "问题识别":
        return "初步接触阶段"
    if "阶段2" in stage:
        return "价值确认阶段"
    if "阶段3" in stage or stage == "解决方案探索":
        return "方案评估阶段"
    if "阶段4" in stage:
        return "招投标准备阶段"
    if "阶段5" in stage or stage == "需求构建":
        return "采购确认阶段"
    if "阶段6" in stage or stage == "已完成":
        return "采购落地阶段"
    return stage if stage and stage != "当前阶段" else "当前推进阶段"


def _topic_text(contact: Dict[str, Any], customer_context: Dict[str, Any]) -> str:
    product = _format_interest(contact.get("product_interests"))
    content = _format_interest(contact.get("top_content_types"))
    return _first_meaningful_value(
        product,
        content,
        customer_context.get("industry"),
        customer_context.get("campaign_tag"),
        default="当前业务需求",
    )


def _case_text(contact: Dict[str, Any], customer_context: Dict[str, Any]) -> str:
    industry = _first_meaningful_value(customer_context.get("industry"), default="")
    product = _format_interest(contact.get("product_interests"))
    campaign = _first_meaningful_value(customer_context.get("campaign_tag"), default="")
    if industry and product:
        return f"{industry}{product}"
    return _first_meaningful_value(industry, product, campaign, default="同类客户")


def _build_recommend_way(contact: Dict[str, Any]) -> str:
    role = contact.get("role_category") or contact.get("purchase_role") or ""
    i30d = int(contact.get("interaction_count_30d") or 0)
    high_value_count = int(contact.get("high_value_count") or 0)
    has_email = bool(contact.get("email"))
    has_mobile = bool(contact.get("mobile"))

    if high_value_count > 0 or i30d >= 3:
        return "先电话或企微承接近期兴趣点，再约 30 分钟沟通"
    if role in {"决策者", "决策层", "拍板者"}:
        return "先发送价值摘要与ROI测算，再约 30 分钟决策沟通"
    if role in {"技术把关", "技术评估者", "关键人"}:
        return "先邮件发送结构化方案，再约 30 分钟技术评估沟通"
    if has_email:
        return "先邮件发送结构化方案，再约 30 分钟沟通"
    if has_mobile:
        return "先电话确认关注方向，再约 30 分钟沟通"
    return "先通过客户经理确认触达方式，再安排 30 分钟沟通"


def _build_rule_priority_recommendation(
    db: Session,
    customer_name: str,
    contact: Dict[str, Any],
    customer_context: Dict[str, Any],
) -> Dict[str, Any]:
    """构建单个规则版优先推进对象。"""
    high_value_count = _fetch_high_value_count(db, customer_name, contact)
    contact["high_value_count"] = high_value_count

    base = _build_rule_recommendation(contact)
    role = base.get("role_category") or base.get("purchase_role") or "联系人"
    i30d = int(base.get("interaction_count_30d") or 0)
    stage = _stage_text(customer_context)
    stage_dialogue = _stage_dialogue_text(stage)
    case = _case_text(base, customer_context)
    name = base.get("contact_name") or "该联系人"

    reason = (
        f"联系人在{stage_dialogue}影响成交节奏；近30天互动 {i30d} 次，"
        f"高价值行为 {high_value_count} 次；"
    )
    if high_value_count == 0 and i30d == 0:
        reason += "暂缺历史行为，适合先做低干扰触达"
    elif high_value_count > 0:
        reason += "已有明确兴趣信号，适合优先推进"
    else:
        reason += "已有互动基础，适合继续培育推进"

    recommend_way = _build_recommend_way(base)
    recommend_script = (
        f"您好{name}，结合贵司当前处于{stage_dialogue}，"
        "我们建议先围绕“方案”做一次30分钟评估，"
        f"现场会带上{case}相关案例与ROI测算，"
        "若方向一致可在本周进入下一步评审。"
    )

    return {
        "contact_name": base.get("contact_name", ""),
        "mobile": base.get("mobile", ""),
        "email": base.get("email", ""),
        "department": base.get("department", ""),
        "position": base.get("position", ""),
        "purchase_role": base.get("purchase_role", ""),
        "role_category": role,
        "relevance_score": round(base.get("ai_relevance_score", base.get("rule_score", 50))),
        "reason": reason,
        "recommend_way": recommend_way,
        "recommend_script": recommend_script,
        "interaction_count_30d": i30d,
        "interaction_count": base.get("interaction_count", 0),
        "high_value_count": high_value_count,
        "last_interaction_time": str(base.get("last_interaction_time", "")),
        "activity_level": base.get("activity_level", ""),
        "intent_level": base.get("intent_level", ""),
        "rule_detail": base.get("rule_detail", {}),
    }


def _build_rule_fallback(contacts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """AI 不可用时，从规则评分结果构建推荐列表。"""
    results: List[Dict[str, Any]] = []
    for c in contacts[:min(len(contacts), AI_CANDIDATE_LIMIT)]:
        results.append(_build_rule_recommendation(c))
    return results


# ─────────────────────────────────────────────────────────────────────────────
# 主入口函数
# ─────────────────────────────────────────────────────────────────────────────

def recommend_priority_contacts(
    db: Session,
    customer_id: str,
    customer_name: str,
    top_n: int = MIN_RECOMMENDATIONS,
) -> Dict[str, Any]:
    """
    规则驱动的优先推进对象推荐主函数。

    工作流程：
    1. 获取该客户的所有联系人数据
    2. 规则评分（角色、互动、最近活跃、信息完整度、意向）
    3. 选出规则分最高的 top_n 名联系人
    4. 基于客户阶段、兴趣主题和行业生成推进方式与话术

    Args:
        db: 数据库会话
        customer_id: 客户 ID
        customer_name: 客户名称（用于回退查询）
        top_n: 最少返回的推荐数量

    Returns:
        {
            "customer_id": str,
            "customer_name": str,
            "recommendation": {...} | None,
            "recommendations": [...],  # 兼容旧数组消费
            "total_candidates": int,
            "source": "rule",
        }
    """
    contacts = _fetch_contacts(db, customer_name, customer_id)

    if not contacts:
        return {
            "customer_id": customer_id,
            "customer_name": customer_name,
            "recommendation": None,
            "recommendations": [],
            "total_candidates": 0,
            "source": "none",
        }

    total_candidates = len(contacts)
    scored_contacts = _compute_rule_scores(contacts)
    customer_context = _fetch_customer_context(db, customer_id)
    limit = max(1, min(int(top_n or MIN_RECOMMENDATIONS), len(scored_contacts)))
    recommendations = [
        _build_rule_priority_recommendation(
            db=db,
            customer_name=customer_name,
            contact=contact,
            customer_context=customer_context,
        )
        for contact in scored_contacts[:limit]
    ]
    recommendation = recommendations[0] if recommendations else None

    return {
        "customer_id": customer_id,
        "customer_name": customer_name,
        "recommendation": recommendation,
        "recommendations": recommendations,
        "total_candidates": total_candidates,
        "source": "rule",
    }
