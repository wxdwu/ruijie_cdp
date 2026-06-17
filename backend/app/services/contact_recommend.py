"""
AI 优先联系人推荐服务

综合考虑角色权重、互动活跃度、最近互动时间、信息完整度等因素，
结合 AI 模型（默认 DeepSeek）生成多维度推荐评分和理由。

设计原则：
- 规则评分作为基础筛选，AI 模型用于最终排序和理由生成
- 模型调用通过抽象层实现，便于切换不同 LLM 提供商
- 当 AI 不可用时自动降级为纯规则模式
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# 配置常量
# ─────────────────────────────────────────────────────────────────────────────

# 默认 AI 模型（可在 .env 中通过 LLM_MODEL_NAME 覆盖）
DEFAULT_MODEL_NAME = "deepseek-chat"

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
MIN_RECOMMENDATIONS = 5
# AI 分析的候选人数上限（选规则分最高的 N 个发送给 AI）
AI_CANDIDATE_LIMIT = 8


# ─────────────────────────────────────────────────────────────────────────────
# 模型抽象层 —— 便于未来切换不同 LLM 提供商
# ─────────────────────────────────────────────────────────────────────────────

class LLMClient:
    """LLM 调用抽象基类，所有 AI 模型调用通过此类进行。"""

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or DEFAULT_MODEL_NAME
        self._client = OpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
        )

    @property
    def is_available(self) -> bool:
        """检查 LLM 是否已配置。"""
        return bool(settings.LLM_API_KEY and settings.LLM_BASE_URL)

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 800,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        调用 LLM 完成对话。

        Args:
            messages: 对话消息列表
            temperature: 温度参数
            max_tokens: 最大 token 数
            response_format: 输出格式（如 {"type": "json_object"}）

        Returns:
            LLM 返回的文本内容，失败返回 None
        """
        if not self.is_available:
            logger.warning("LLM 未配置，跳过 AI 调用")
            return None

        try:
            kwargs: Dict[str, Any] = {
                "model": self.model_name,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if response_format:
                kwargs["response_format"] = response_format

            response = self._client.chat.completions.create(**kwargs)
            return response.choices[0].message.content

        except Exception as e:
            logger.warning("LLM 调用失败: %s", e)
            return None


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
            "SELECT customer_name, industry, purchase_stage, intent_level, "
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
    AI 驱动的优先联系人推荐主函数。

    工作流程：
    1. 获取该客户的所有联系人数据
    2. 规则评分（角色、互动、最近活跃、信息完整度、意向）
    3. 如果 N > 0 且 LLM 可用，发送 top-k 候选给 AI 做最终排序和理由生成
    4. 如果 AI 不可用或失败，降级为纯规则推荐
    5. 确保至少返回 top_n 个推荐

    Args:
        db: 数据库会话
        customer_id: 客户 ID
        customer_name: 客户名称（用于回退查询）
        top_n: 最少返回的推荐数量

    Returns:
        {
            "customer_id": str,
            "customer_name": str,
            "recommendations": [...],  # 推荐列表，按相关性降序
            "total_candidates": int,
            "source": "ai" | "rule",
        }
    """
    # 1. 获取数据
    contacts = _fetch_contacts(db, customer_name, customer_id)

    if not contacts:
        return {
            "customer_id": customer_id,
            "customer_name": customer_name,
            "recommendations": [],
            "total_candidates": 0,
            "source": "none",
        }

    total_candidates = len(contacts)

    # 2. 规则评分
    scored_contacts = _compute_rule_scores(contacts)

    # 3. AI 二次分析（取规则分最高的 N 个候选发给 AI）
    llm = LLMClient()
    source = "rule"

    if llm.is_available and len(scored_contacts) >= 1:
        candidates_for_ai = scored_contacts[:AI_CANDIDATE_LIMIT]
        customer_context = _fetch_customer_context(db, customer_id)

        ai_response = llm.chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": "你是一位专业的 B2B 销售顾问。请严格按照 JSON 格式输出推荐结果。",
                },
                {
                    "role": "user",
                    "content": _build_ai_prompt(candidates_for_ai, customer_context),
                },
            ],
            temperature=0.3,
            max_tokens=1000,
            response_format={"type": "json_object"},
        )

        if ai_response:
            recommendations, source = _parse_ai_response(ai_response, scored_contacts)
        else:
            recommendations = _build_rule_fallback(scored_contacts)
    else:
        recommendations = _build_rule_fallback(scored_contacts)

    # 4. 确保返回足够的推荐数
    if len(recommendations) < top_n and len(scored_contacts) > len(recommendations):
        recommended_names = {r.get("contact_name") for r in recommendations}
        for c in scored_contacts:
            if len(recommendations) >= top_n:
                break
            if c.get("contact_name") not in recommended_names:
                recommendations.append(_build_rule_recommendation(c))
                recommended_names.add(c.get("contact_name"))

    # 5. 最终排序
    recommendations.sort(
        key=lambda x: x.get("ai_relevance_score", x.get("rule_score", 0)),
        reverse=True,
    )

    # 6. 截断到 top_n 个（不足则全量返回）
    recommendations = recommendations[:min(len(recommendations), top_n)]

    # 7. 清理输出字段（移除内部字段，只保留前端需要的）
    clean_recommendations: List[Dict[str, Any]] = []
    for rec in recommendations:
        clean_recommendations.append({
            "contact_name": rec.get("contact_name", ""),
            "mobile": rec.get("mobile", ""),
            "email": rec.get("email", ""),
            "department": rec.get("department", ""),
            "position": rec.get("position", ""),
            "purchase_role": rec.get("purchase_role", ""),
            "role_category": rec.get("role_category", ""),
            "relevance_score": rec.get("ai_relevance_score", rec.get("rule_score", 50)),
            "reason": rec.get("reason", ""),
            "interaction_count_30d": rec.get("interaction_count_30d", 0),
            "interaction_count": rec.get("interaction_count", 0),
            "last_interaction_time": str(rec.get("last_interaction_time", "")),
            "activity_level": rec.get("activity_level", ""),
            "intent_level": rec.get("intent_level", ""),
        })

    return {
        "customer_id": customer_id,
        "customer_name": customer_name,
        "recommendations": clean_recommendations,
        "total_candidates": total_candidates,
        "source": source,
    }
