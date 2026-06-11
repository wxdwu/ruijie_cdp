"""
AI Chat router with NL2SQL entity parsing.

Provides endpoints for:
- POST /api/ai/parse - Parse natural language to extract entities
- POST /api/ai/chat - Return AI response + customer list results
- POST /api/ai/chat/export - Export chat query results
"""

from __future__ import annotations

import io
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["ai"])


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Models
# ─────────────────────────────────────────────────────────────────────────────

class ParseRequest(BaseModel):
    query: Optional[str] = None
    text: Optional[str] = None

    def get_query(self) -> str:
        return self.query or self.text or ""


class ChatRequest(BaseModel):
    query: Optional[str] = None
    text: Optional[str] = None
    history: Optional[List[Dict[str, Any]]] = None

    def get_query(self) -> str:
        return self.query or self.text or ""


class ChatExportRequest(BaseModel):
    query: str
    entities: Dict[str, Any]


class ExtractedEntities(BaseModel):
    industry: Optional[str] = None
    region: Optional[str] = None
    stage: Optional[str] = None
    intent_level: Optional[str] = None
    channel: Optional[str] = None
    keyword: Optional[str] = None
    interaction_min: Optional[int] = None


# ─────────────────────────────────────────────────────────────────────────────
# Entity Parsing Logic (Rule-based)
# ─────────────────────────────────────────────────────────────────────────────

# Industry keywords and their mappings
INDUSTRY_KEYWORDS = {
    "医疗": ["医疗", "医院", "诊所", "健康", "医药"],
    "企业": ["企业", "公司", "集团", "制造", "工业"],
    "政府": ["政府", "政务", "机关", "事业单位", "公共部门"],
    "教育": ["教育", "学校", "大学", "学院", "培训", "高校"],
    "金融": ["金融", "银行", "证券", "保险", "投资"],
    "零售": ["零售", "电商", "商店", "超市"],
    "科技": ["科技", "互联网", "软件", "IT", "技术"],
}

# Region keywords
REGION_KEYWORDS = {
    "广东": ["广东", "广州", "深圳", "东莞", "佛山", "珠海"],
    "北京": ["北京", "京城", "帝都"],
    "上海": ["上海", "魔都", "沪上"],
    "浙江": ["浙江", "杭州", "宁波", "温州"],
    "江苏": ["江苏", "南京", "苏州", "无锡"],
    "四川": ["四川", "成都", "重庆"],
    "湖北": ["湖北", "武汉"],
    "山东": ["山东", "济南", "青岛"],
    "河南": ["河南", "郑州"],
    "福建": ["福建", "厦门", "福州"],
}

# Stage keywords
STAGE_KEYWORDS = {
    "问题识别": ["问题识别", "识别问题", "发现问题", "问题阶段"],
    "解决方案探索": ["解决方案", "方案探索", "寻找方案", "方案阶段", "解决"],
    "需求构建": ["需求构建", "构建需求", "需求明确", "需求阶段", "明确需求"],
    "方案评估": ["方案评估", "评估方案", "评估阶段"],
    "商务谈判": ["商务谈判", "谈判", "商务阶段", "合同"],
    "成交": ["成交", "签约", "签单", "合作"],
}

# Intent level keywords
INTENT_LEVEL_KEYWORDS = {
    "高": ["高", "高意向", "强烈", "非常感兴趣"],
    "中": ["中", "中等", "一般", "还行"],
    "低": ["低", "低意向", "弱", "不感兴趣"],
}

# Channel keywords
CHANNEL_KEYWORDS = {
    "官网": ["官网", "网站", "网页", "官方网站"],
    "直播": ["直播", "直播间", "线上直播", "视频直播"],
    "邮件": ["邮件", "邮箱", "电子邮件", "email"],
    "微信": ["微信", "公众号", "小程序", "wechat"],
    "电话": ["电话", "来电", "呼叫", "phone"],
    "展会": ["展会", "展览", "线下活动", "博览会"],
}


def extract_entities(query: str) -> ExtractedEntities:
    """Extract entities from natural language query using rule-based matching."""
    entities = ExtractedEntities()

    # Extract industry
    for industry, keywords in INDUSTRY_KEYWORDS.items():
        for kw in keywords:
            if kw in query:
                entities.industry = industry
                break
        if entities.industry:
            break

    # Extract region
    for region, keywords in REGION_KEYWORDS.items():
        for kw in keywords:
            if kw in query:
                entities.region = region
                break
        if entities.region:
            break

    # Extract stage
    for stage, keywords in STAGE_KEYWORDS.items():
        for kw in keywords:
            if kw in query:
                entities.stage = stage
                break
        if entities.stage:
            break

    # Extract intent level
    for intent_level, keywords in INTENT_LEVEL_KEYWORDS.items():
        for kw in keywords:
            if kw in query:
                entities.intent_level = intent_level
                break
        if entities.intent_level:
            break

    # Extract channel
    for channel, keywords in CHANNEL_KEYWORDS.items():
        for kw in keywords:
            if kw in query:
                entities.channel = channel
                break
        if entities.channel:
            break

    # Extract interaction_min: look for patterns like "互动3次以上", "3次互动", "至少3次"
    interaction_patterns = [
        r"互动(\d+)次",
        r"(\d+)次互动",
        r"至少(\d+)次",
        r"(\d+)次以上",
        r"互动次数[^\d]*(\d+)",
    ]
    for pattern in interaction_patterns:
        match = re.search(pattern, query)
        if match:
            entities.interaction_min = int(match.group(1))
            break

    # Extract keyword (company name fragment) - look for company-like patterns
    # Simple heuristic: look for "公司", "企业", "集团" followed by name
    # Or quoted text that might be a company name
    keyword_patterns = [
        r'["“]([^"”]+)["”]',  # Quoted text
        r'([^\s，。！？、]+公司)',  # X公司
        r'([^\s，。！？、]+集团)',  # X集团
        r'([^\s，。！？、]+科技)',  # X科技
    ]
    for pattern in keyword_patterns:
        match = re.search(pattern, query)
        if match:
            entities.keyword = match.group(1)
            break

    return entities


def generate_ai_response(query: str, entities: ExtractedEntities, total: int) -> str:
    """Generate a natural language AI response based on extracted entities."""
    response_parts = []

    # Opening
    response_parts.append(f"我已理解您的查询：「{query}」")

    # Entity summary
    extracted = []
    if entities.industry:
        extracted.append(f"行业：{entities.industry}")
    if entities.region:
        extracted.append(f"区域：{entities.region}")
    if entities.stage:
        extracted.append(f"阶段：{entities.stage}")
    if entities.intent_level:
        extracted.append(f"意向等级：{entities.intent_level}")
    if entities.channel:
        extracted.append(f"渠道：{entities.channel}")
    if entities.interaction_min:
        extracted.append(f"互动次数：≥{entities.interaction_min}次")
    if entities.keyword:
        extracted.append(f"关键词：{entities.keyword}")

    if extracted:
        response_parts.append("\n已识别以下筛选条件：")
        response_parts.extend([f"• {item}" for item in extracted])
    else:
        response_parts.append("\n未识别到特定筛选条件，将返回全部客户。")

    # Result summary
    response_parts.append(f"\n共找到 {total} 个匹配的客户，您可以查看下方列表或导出数据。")

    return "\n".join(response_parts)


# ─────────────────────────────────────────────────────────────────────────────
# Database Query
# ─────────────────────────────────────────────────────────────────────────────

def query_customers_by_entities(
    db: Session,
    entities: ExtractedEntities,
    page: int = 1,
    page_size: int = 50,
) -> Dict[str, Any]:
    """Query dws_customer_360 using extracted entities as filters."""
    where_parts: List[str] = ["1=1"]
    params: Dict[str, Any] = {}

    if entities.industry:
        where_parts.append("industry = :industry")
        params["industry"] = entities.industry
    if entities.region:
        where_parts.append("region = :region")
        params["region"] = entities.region
    if entities.stage:
        where_parts.append("purchase_stage = :stage")
        params["stage"] = entities.stage
    if entities.intent_level:
        where_parts.append("intent_level = :intent_level")
        params["intent_level"] = entities.intent_level
    if entities.channel:
        where_parts.append("last_interaction_channel = :channel")
        params["channel"] = entities.channel
    if entities.keyword:
        where_parts.append(
            "(customer_name LIKE :kw OR company_name LIKE :kw)"
        )
        params["kw"] = f"%{entities.keyword}%"
    if entities.interaction_min is not None:
        where_parts.append("interaction_count_30d >= :interaction_min")
        params["interaction_min"] = entities.interaction_min

    where_sql = " AND ".join(where_parts)

    # Count
    count_sql = text(f"SELECT COUNT(*) FROM dws_customer_360 WHERE {where_sql}")
    total: int = db.execute(count_sql, params).scalar() or 0

    # Data
    offset = (max(1, page) - 1) * page_size
    data_sql = text(
        f"SELECT * FROM dws_customer_360 "
        f"WHERE {where_sql} "
        f"ORDER BY intent_score DESC "
        f"LIMIT :limit OFFSET :offset"
    )
    params["limit"] = page_size
    params["offset"] = offset

    rows = db.execute(data_sql, params).mappings().all()
    items = [dict(r) for r in rows]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/parse")
def parse_natural_language(
    request: ParseRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Parse natural language query and extract entities."""
    q = request.get_query()
    if not q:
        return {"query": "", "entities": {}}
    entities = extract_entities(q)
    return {
        "query": q,
        "entities": entities.dict(exclude_none=True),
    }


@router.post("/chat")
def chat(
    request: ChatRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Process chat query and return AI response + customer results."""
    # Extract entities
    q = request.get_query()
    if not q:
        return {"entities": {}, "results": [], "total": 0, "response": "请输入查询内容"}
    entities = extract_entities(q)

    # Query customers
    result = query_customers_by_entities(db, entities)

    # Generate AI response
    ai_response = generate_ai_response(request.query, entities, result["total"])

    return {
        "query": request.query,
        "entities": entities.dict(exclude_none=True),
        "response": ai_response,
        "customers": result,
    }


@router.post("/chat/export")
def export_chat_results(
    request: ChatExportRequest,
    db: Session = Depends(get_db),
) -> Response:
    """Export chat query results to Excel."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="openpyxl not installed. Please install openpyxl for Excel export.",
        )

    # Create entities object
    entities = ExtractedEntities(**request.entities)

    # Query all matching customers
    result = query_customers_by_entities(db, entities, page=1, page_size=10000)
    items = result["items"]

    # Create Excel
    wb = Workbook()
    ws = wb.active
    ws.title = "AI查询结果"

    # Export columns
    columns = [
        ("customer_id", "客户ID", 18),
        ("customer_name", "客户名称", 25),
        ("company_name", "公司名称", 30),
        ("industry", "行业", 15),
        ("region", "区域", 12),
        ("purchase_stage", "购买阶段", 15),
        ("intent_level", "意向等级", 12),
        ("intent_score", "意向评分", 12),
        ("interaction_count_30d", "30天互动", 12),
        ("last_interaction_channel", "最近渠道", 12),
        ("last_interaction_time", "最近互动", 20),
    ]

    # Header style
    header_font = Font(name="微软雅黑", bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9"),
    )

    # Write headers
    for col_idx, (field, label, width) in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=col_idx, value=label)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border
        ws.column_dimensions[cell.column_letter].width = width

    # Write data
    data_font = Font(name="微软雅黑", size=10)
    data_align = Alignment(vertical="center")

    for row_idx, item in enumerate(items, start=2):
        for col_idx, (field, _label, _width) in enumerate(columns, start=1):
            value = item.get(field, "")
            if isinstance(value, datetime):
                value = value.strftime("%Y-%m-%d %H:%M")
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.font = data_font
            cell.alignment = data_align
            cell.border = thin_border

    ws.freeze_panes = "A2"
    last_col = ws.cell(row=1, column=len(columns)).column_letter
    ws.auto_filter.ref = f"A1:{last_col}{len(items) + 1}"

    # Write to bytes
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="ai_chat_export.xlsx"',
        },
    )
