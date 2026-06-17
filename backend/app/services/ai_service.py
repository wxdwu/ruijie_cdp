"""
AI Service - 完整的 AI 对话功能实现

功能模块：
1. 用户输入预处理
2. 意图识别（预处理和意图识别共调用一次模型）
3. 核心业务处理（根据用户问答获取，生成SQL查询）
4. SQL结果输出转化（将SQL结果喂给大模型分析）
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 文本预处理模块
# ─────────────────────────────────────────────────────────────────────────────

# 口语化表达替换词典
COLLOQUIAL_REPLACEMENTS = {
    r"帮我找": "查找",
    r"帮我看": "查询",
    r"帮我看看": "查询",
    r"我想找": "查找",
    r"我要找": "查找",
    r"有没有": "是否存在",
    r"有哪些": "列出",
    r"是多少": "的数值",
    r"怎么样": "的情况",
    r"如何": "怎样",
    r"为啥": "为什么",
    r"咋": "怎么",
}

# 停用词列表
STOP_WORDS = {"的", "了", "呢", "啊", "哦", "嗯", "吧", "嘛", "呢", "吗"}


def preprocess_text(text: str, history: Optional[List[Dict]] = None) -> str:
    """
    预处理用户输入文本
    
    处理过程：
    1. 文本清洗（去除多余空格、特殊字符）
    2. 口语化内容替换
    3. 根据上下文补全代词
    
    Args:
        text: 用户输入文本
        history: 对话历史，用于补全代词
        
    Returns:
        预处理后的文本
    """
    if not text:
        return ""
    
    # 1. 文本清洗
    text = text.strip()
    text = re.sub(r"\s+", " ", text)  # 合并多个空格
    text = re.sub(r"[^\w\s\u4e00-\u9fff，。！？、；：""''（）]", "", text)  # 保留中文字符和标点
    
    # 2. 口语化表达替换
    for pattern, replacement in COLLOQUIAL_REPLACEMENTS.items():
        text = re.sub(pattern, replacement, text)
    
    # 3. 去除停用词（可选，这里保留停用词以维持语义）
    # text = "".join(char for char in text if char not in STOP_WORDS)
    
    # 4. 根据上下文补全代词
    if history and len(history) > 0:
        # 获取最近的用户输入
        recent_user_inputs = [msg["text"] for msg in history if msg["role"] == "user"]
        if recent_user_inputs:
            last_input = recent_user_inputs[-1]
            # 如果当前输入以"它"、"他们"、"这些"等代词开头，尝试补全
            pronoun_pattern = r"^(它|他们|这些|那些|这个|那个)\s*"
            match = re.match(pronoun_pattern, text)
            if match:
                pronoun = match.group(1)
                # 从上一轮输入中提取关键信息（如公司名、行业等）
                # 这里简单处理：直接使用上一轮输入作为上下文
                text = f"{last_input}的{pronoun}" + text[len(pronoun):]
    
    return text


# ─────────────────────────────────────────────────────────────────────────────
# 意图识别模块
# ─────────────────────────────────────────────────────────────────────────────

def recognize_intent(text: str, history: Optional[List[Dict]] = None) -> Dict[str, Any]:
    """
    识别用户意图
    
    调用 DeepSeek 模型进行意图识别，共分为三类：
    1. business_query: 业务查询（需要查询数据库）
    2. simple_question: 简单问题（可以直接回答）
    3. other: 其他问题（通用回答）
    
    Args:
        text: 预处理后的文本
        history: 对话历史
        
    Returns:
        包含意图和结构化查询的字典
    """
    if not text:
        return {"intent": "other", "structured_query": {}}
    
    # 构建对话历史
    messages = [
        {
            "role": "system",
            "content": """你是一个智能客户查询助手。根据用户的问题，判断意图并提取结构化查询条件。

输出格式必须是 JSON，包含以下字段：
- "intent": 意图类型，只能是 "business_query"（业务查询）、"simple_question"（简单问题）或 "other"（其他）
- "structured_query": 如果是业务查询，包含结构化的查询条件；否则为空对象

业务查询的结构化查询条件可能包括：
- "industry": 行业（如 "医疗"、"教育"、"金融"）
- "region": 区域（如 "广东"、"北京"、"上海"）
- "stage": 采购阶段（如 "问题识别"、"解决方案探索"、"需求构建"）
- "intent_level": 意向等级（如 "高"、"中"、"低"）
- "channel": 互动渠道（如 "官网"、"微信"、"邮件"）
- "keyword": 关键词（公司名称或客户名称的一部分）
- "interaction_min": 最小互动次数（整数）

示例输入1: "查找广东地区医疗行业高意向的客户"
示例输出1: {"intent": "business_query", "structured_query": {"industry": "医疗", "region": "广东", "intent_level": "高"}}

示例输入2: "你好"
示例输出2: {"intent": "simple_question", "structured_query": {}}

示例输入3: "今天天气怎么样"
示例输出3: {"intent": "other", "structured_query": {}}

只输出 JSON，不要输出其他内容。
""",
        }
    ]
    
    # 添加对话历史
    if history:
        for msg in history[-5:]:  # 只保留最近5轮对话
            messages.append({
                "role": "user" if msg["role"] == "user" else "assistant",
                "content": msg["text"],
            })
    
    # 添加当前问题
    messages.append({"role": "user", "content": text})
    
    try:
        # 调用 DeepSeek API
        client = OpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
        )
        
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            response_format={"type": "json_object"},  # 强制输出 JSON
            temperature=0.1,  # 低温度，提高准确性
            max_tokens=500,
        )
        
        # 解析响应
        content = response.choices[0].message.content
        result = json.loads(content)
        
        # 验证结果格式
        if "intent" not in result:
            result["intent"] = "other"
        if "structured_query" not in result:
            result["structured_query"] = {}
        
        return result
        
    except Exception as e:
        logger.error("意图识别失败: %s", e)
        # 降级处理：默认为其他问题
        return {"intent": "other", "structured_query": {}}


# ─────────────────────────────────────────────────────────────────────────────
# SQL 生成模块
# ─────────────────────────────────────────────────────────────────────────────

def generate_sql(structured_query: Dict[str, Any]) -> Tuple[str, str, Dict[str, Any]]:
    """
    根据结构化查询生成 SQL
    
    不调用大模型，直接使用规则生成 SQL，提高响应速度。
    
    Args:
        structured_query: 结构化查询条件
        
    Returns:
        (count_sql, data_sql, params): 计数SQL、数据SQL和参数
    """
    if not structured_query:
        return (
            "SELECT COUNT(*) FROM dws_customer_360 WHERE 1=1",
            "SELECT * FROM dws_customer_360 WHERE 1=1 ORDER BY intent_score DESC LIMIT :limit OFFSET :offset",
            {}
        )
    
    where_parts = ["1=1"]
    params = {}
    
    # 行业
    if "industry" in structured_query and structured_query["industry"]:
        where_parts.append("industry = :industry")
        params["industry"] = structured_query["industry"]
    
    # 区域
    if "region" in structured_query and structured_query["region"]:
        where_parts.append("region = :region")
        params["region"] = structured_query["region"]
    
    # 采购阶段
    if "stage" in structured_query and structured_query["stage"]:
        where_parts.append("purchase_stage = :stage")
        params["stage"] = structured_query["stage"]
    
    # 意向等级
    if "intent_level" in structured_query and structured_query["intent_level"]:
        where_parts.append("intent_level = :intent_level")
        params["intent_level"] = structured_query["intent_level"]
    
    # 互动渠道
    if "channel" in structured_query and structured_query["channel"]:
        where_parts.append("last_interaction_channel = :channel")
        params["channel"] = structured_query["channel"]
    
    # 关键词（模糊匹配客户名称）
    if "keyword" in structured_query and structured_query["keyword"]:
        where_parts.append("customer_name LIKE :keyword")
        params["keyword"] = f"%{structured_query['keyword']}%"
    
    # 最小互动次数
    if "interaction_min" in structured_query and structured_query["interaction_min"] is not None:
        where_parts.append("interaction_count_30d >= :interaction_min")
        params["interaction_min"] = structured_query["interaction_min"]
    
    where_sql = " AND ".join(where_parts)
    
    # 生成查询 SQL（包含计数）
    count_sql = f"SELECT COUNT(*) FROM dws_customer_360 WHERE {where_sql}"
    data_sql = f"SELECT * FROM dws_customer_360 WHERE {where_sql} ORDER BY intent_score DESC LIMIT :limit OFFSET :offset"
    
    return count_sql, data_sql, params


def execute_sql(db: Session, count_sql: str, data_sql: str, params: Dict[str, Any], 
                page: int = 1, page_size: int = 50) -> Dict[str, Any]:
    """
    执行 SQL 查询
    
    Args:
        db: 数据库会话
        count_sql: 计数 SQL
        data_sql: 数据查询 SQL
        params: SQL 参数
        page: 页码
        page_size: 每页大小
        
    Returns:
        查询结果（包含 total, items, page, page_size）
    """
    # 计数查询
    count_params = {k: v for k, v in params.items() if k not in ["limit", "offset"]}
    total = db.execute(text(count_sql), count_params).scalar() or 0
    
    # 数据查询
    offset = (max(1, page) - 1) * page_size
    query_params = {**params, "limit": page_size, "offset": offset}
    rows = db.execute(text(data_sql), query_params).mappings().all()
    items = [dict(r) for r in rows]
    
    return {
        "total": total,
        "items": items,
        "page": page,
        "page_size": page_size,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 结果分析模块
# ─────────────────────────────────────────────────────────────────────────────

def analyze_results(query: str, sql_results: Dict[str, Any], 
                    structured_query: Dict[str, Any]) -> str:
    """
    将 SQL 结果喂给大模型分析，生成前端回复
    
    Args:
        query: 用户原始查询
        sql_results: SQL 查询结果
        structured_query: 结构化查询条件
        
    Returns:
        前端回复内容（包含导出功能提示）
    """
    if not sql_results or sql_results.get("total", 0) == 0:
        return f"未找到匹配的客户。请尝试调整查询条件。"
    
    # 构建分析结果提示词
    total = sql_results["total"]
    items = sql_results["items"][:10]  # 只取前10条用于分析
    
    # 简化结果数据（只保留关键字段）
    simplified_items = []
    for item in items:
        simplified_items.append({
            "customer_name": item.get("customer_name", ""),
            "industry": item.get("industry", ""),
            "purchase_stage": item.get("purchase_stage", ""),
            "intent_level": item.get("intent_level", ""),
            "intent_score": item.get("intent_score", 0),
            "interaction_count_30d": item.get("interaction_count_30d", 0),
            "last_interaction_channel": item.get("last_interaction_channel", ""),
        })
    
    prompt = f"""
用户查询: {query}

查询条件: {json.dumps(structured_query, ensure_ascii=False)}

查询结果: 共找到 {total} 个客户，以下是前 10 条数据：
{json.dumps(simplified_items, ensure_ascii=False, indent=2)}

请生成一段友好的回复，包含以下内容：
1. 简要总结查询结果（如客户数量、主要行业分布等）
2. 突出显示关键信息（如高意向客户、即将成交的客户等）
3. 建议下一步操作（如查看客户详情、导出数据等）
4. 使用自然、专业的语气

回复要简洁明了，不超过200字。
"""
    
    try:
        # 调用 DeepSeek API
        client = OpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
        )
        
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一个专业的客户分析助手，擅长从数据中提取洞察并给出建议。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=500,
        )
        
        analysis = response.choices[0].message.content or ""
        
        # 添加导出提示
        export_hint = f'\n\n💡 提示：您可以点击"导出"按钮将全部 {total} 条结果导出为 Excel 文件。'
        
        return analysis + export_hint
        
    except Exception as e:
        logger.error("结果分析失败: %s", e)
        # 降级处理：返回简单结果
        return f'找到 {total} 个匹配的客户。您可以查看下方列表或点击"导出"按钮下载完整数据。'


# ─────────────────────────────────────────────────────────────────────────────
# 简单问题回答模块
# ─────────────────────────────────────────────────────────────────────────────

def answer_simple_question(question: str) -> str:
    """
    回答简单问题（不查询数据库）
    
    Args:
        question: 用户问题
        
    Returns:
        回答内容
    """
    try:
        client = OpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
        )
        
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一个友好的对话助手。回答用户的问题，保持简洁友好。"},
                {"role": "user", "content": question},
            ],
            temperature=0.7,
            max_tokens=300,
        )
        
        return response.choices[0].message.content or "抱歉，我暂时无法回答这个问题。"
        
    except Exception as e:
        logger.error("简单问题回答失败: %s", e)
        return "抱歉，我暂时无法回答这个问题。请尝试询问客户查询相关的问题。"


# ─────────────────────────────────────────────────────────────────────────────
# 通用回答模块
# ─────────────────────────────────────────────────────────────────────────────

def answer_other_question(question: str) -> str:
    """
    通用回答（其他问题）
    
    Args:
        question: 用户问题
        
    Returns:
        回答内容
    """
    try:
        client = OpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
        )
        
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": """你是一个客户查询系统的助手。

如果用户的问题与客户查询无关，礼貌地引导用户使用系统的主要功能：
1. 查询客户（如"查找广东地区医疗行业高意向的客户"）
2. 查看客户详情
3. 导出客户数据

保持回答简洁友好，不超过100字。"""},
                {"role": "user", "content": question},
            ],
            temperature=0.7,
            max_tokens=200,
        )
        
        return response.choices[0].message.content or "我是您的客户查询助手，请尝试询问客户查询相关的问题。"
        
    except Exception as e:
        logger.error("通用回答失败: %s", e)
        return '我是您的客户查询助手。您可以尝试询问我关于客户查询的问题，比如"查找广东地区医疗行业的高意向客户"。'


# ─────────────────────────────────────────────────────────────────────────────
# 主流程：完整对话处理
# ─────────────────────────────────────────────────────────────────────────────

def process_chat(query: str, history: Optional[List[Dict]] = None, 
                 db: Optional[Session] = None) -> Dict[str, Any]:
    """
    完整的对话处理流程
    
    处理步骤：
    1. 用户输入预处理
    2. 意图识别
    3. 根据意图分别处理：
       - business_query: 生成SQL → 查询数据库 → 分析结果
       - simple_question: 直接回答
       - other: 通用回答
    
    Args:
        query: 用户输入
        history: 对话历史
        db: 数据库会话（仅业务查询需要）
        
    Returns:
        包含查询结果和回复的字典
    """
    # 1. 预处理
    preprocessed_query = preprocess_text(query, history)
    logger.info("预处理结果: %s -> %s", query, preprocessed_query)
    
    # 2. 意图识别
    intent_result = recognize_intent(preprocessed_query, history)
    intent = intent_result.get("intent", "other")
    structured_query = intent_result.get("structured_query", {})
    
    logger.info("意图识别结果: intent=%s, structured_query=%s", intent, structured_query)
    
    # 3. 根据意图处理
    if intent == "business_query":
        # 业务查询：生成SQL → 查询数据库 → 分析结果
        if not db:
            return {
                "query": query,
                "preprocessed_query": preprocessed_query,
                "intent": intent,
                "structured_query": structured_query,
                "response": "系统错误：缺少数据库连接。",
                "customers": {"total": 0, "items": [], "page": 1, "page_size": 50},
            }
        
        # 生成SQL
        count_sql, data_sql, params = generate_sql(structured_query)

        # ── 调试输出 ──
        print("=" * 60)
        print("[DEBUG] 结构化查询条件:", json.dumps(structured_query, ensure_ascii=False))
        print("[DEBUG] count_sql:", count_sql)
        print("[DEBUG] data_sql:", data_sql)
        print("[DEBUG] SQL 参数:", params)
        print("=" * 60)

        # 执行查询
        sql_results = execute_sql(db, count_sql, data_sql, params)
        
        # 分析结果
        response = analyze_results(query, sql_results, structured_query)
        
        return {
            "query": query,
            "preprocessed_query": preprocessed_query,
            "intent": intent,
            "structured_query": structured_query,
            "response": response,
            "customers": sql_results,
        }
        
    elif intent == "simple_question":
        # 简单问题：直接回答
        response = answer_simple_question(preprocessed_query)
        
        return {
            "query": query,
            "preprocessed_query": preprocessed_query,
            "intent": intent,
            "structured_query": {},
            "response": response,
            "customers": {"total": 0, "items": [], "page": 1, "page_size": 50},
        }
        
    else:
        # 其他问题：通用回答
        response = answer_other_question(preprocessed_query)
        
        return {
            "query": query,
            "preprocessed_query": preprocessed_query,
            "intent": intent,
            "structured_query": {},
            "response": response,
            "customers": {"total": 0, "items": [], "page": 1, "page_size": 50},
        }


# ─────────────────────────────────────────────────────────────────────────────
# 导出功能
# ─────────────────────────────────────────────────────────────────────────────

def export_query_results(structured_query: Dict[str, Any], db: Session) -> bytes:
    """
    导出查询结果为 Excel
    
    Args:
        structured_query: 结构化查询条件
        db: 数据库会话
        
    Returns:
        Excel 文件的二进制数据
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
        import io
        from datetime import datetime
        
        # 生成SQL（仅使用数据查询SQL，不需要计数SQL）
        _, data_sql, params = generate_sql(structured_query)
        
        # 执行查询（导出所有结果）
        offset = 0
        limit = 10000  # 最大导出10000条
        query_params = {**params, "limit": limit, "offset": offset}
        rows = db.execute(text(data_sql), query_params).mappings().all()
        items = [dict(r) for r in rows]
        
        # 创建Excel
        wb = Workbook()
        ws = wb.active
        ws.title = "AI查询结果"
        
        # 定义导出列
        columns = [
            ("customer_name", "客户名称", 25),
            ("industry", "行业", 15),
            ("region", "区域", 12),
            ("purchase_stage", "采购阶段", 15),
            ("intent_level", "意向等级", 12),
            ("intent_score", "意向评分", 12),
            ("interaction_count_30d", "30天互动", 12),
            ("interaction_count_total", "总互动", 12),
            ("last_interaction_channel", "最近渠道", 12),
            ("last_interaction_time", "最近互动时间", 20),
            ("active_opp_amount", "机会金额", 15),
            ("owner_name", "负责人", 15),
        ]
        
        # 表头样式
        header_font = Font(name="微软雅黑", bold=True, color="FFFFFF", size=11)
        header_fill = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
        header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
        thin_border = Border(
            left=Side(style="thin", color="D9D9D9"),
            right=Side(style="thin", color="D9D9D9"),
            top=Side(style="thin", color="D9D9D9"),
            bottom=Side(style="thin", color="D9D9D9"),
        )
        
        # 写入表头
        for col_idx, (field, label, width) in enumerate(columns, start=1):
            cell = ws.cell(row=1, column=col_idx, value=label)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align
            cell.border = thin_border
            ws.column_dimensions[cell.column_letter].width = width
        
        # 写入数据
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
        
        # 保存到字节流
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        
        return buf.getvalue()
        
    except Exception as e:
        logger.error("导出失败: %s", e)
        raise
