"""
AI Service - 完整的 AI 对话功能实现

功能模块：
1. 用户输入预处理
2. 意图识别（预处理和意图识别共调用一次模型）
3. 核心业务处理（根据用户问答获取，生成SQL查询）
4. SQL结果输出转化（将SQL结果喂给大模型分析）

优化说明（2026-06-24）：
- 扩展实体提取：支持所有 dws_customer_360 字段
- 支持多表查询：dws_customer_360, dws_contact_360, dws_contact_mapping, dws_interaction_detail
- 智能数据充足性判断：明确告知用户哪些数据查到了，哪些没有
"""

import json
import logging
import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# 数据库表结构定义
# ─────────────────────────────────────────────────────────────────────────────

# dws_customer_360 表字段及说明
CUSTOMER_360_FIELDS = {
    "customer_name": "客户公司名称",
    "industry": "所属行业",
    "region": "地域/区域",
    "owner_name": "公司拥有者名称/负责人",
    "campaign_tag": "活动标签",
    "purchase_stage": "发展阶段/采购阶段",
    "forecast_type": "预测类型",
    "role_coverage": "人员覆盖度（完整/部分/无）",
    "intent_score": "意向评分（0-100）",
    "intent_level": "意向等级（高/中/低）",
    "interaction_count_30d": "近30天互动次数",
    "interaction_count_total": "总互动次数",
    "last_interaction_time": "最近一次交互时间",
    "last_interaction_channel": "最近互动渠道",
    "active_opp_count": "活跃商机数量",
    "active_opp_amount": "活跃商机金额",
    "funnel_opp_count": "漏斗商机数量",
    "won_amount": "已中标金额",
    "contact_count": "公司联系人总数",
    "mobile_count": "手机号数量",
    "is_existing_customer": "是否现有客户（0/1）",
}

# dws_contact_360 表字段及说明
CONTACT_360_FIELDS = {
    "customer_id": "客户ID",
    "contact_name": "联系人姓名",
    "mobile": "手机号",
    "email": "邮箱",
    "department": "部门",
    "position": "职位",
    "purchase_role": "采购角色",
    "role_category": "角色类别（决策者/技术评估者/使用者/其他）",
    "interaction_count": "总互动次数",
    "interaction_count_30d": "近30天互动次数",
    "last_interaction_time": "最近互动时间",
    "activity_level": "活跃度等级",
    "intent_level": "意向等级",
    "lead_stage": "线索阶段",
}

# dws_contact_mapping 表字段及说明
CONTACT_MAPPING_FIELDS = {
    "customer_name": "客户公司名称",
    "contact_name": "联系人姓名",
    "mobile": "手机号",
    "email": "邮箱",
    "department": "部门",
    "position": "职位",
    "purchase_role": "采购角色",
    "role_category": "角色类别",
    "source_table": "来源表",
    "linkflow_contact_id": "Linkflow联系人ID",
    "zhique_matched": "是否已匹配智能体",
}

# dws_interaction_detail 表字段及说明
INTERACTION_DETAIL_FIELDS = {
    "customer_name": "客户公司名称",
    "contact_name": "联系人姓名",
    "mobile": "手机号",
    "source_table": "来源表",
    "channel": "互动渠道（官网/微信/邮件/活动）",
    "behavior_type": "行为类型",
    "content": "互动内容",
    "event_time": "互动时间",
    "is_high_value": "是否高价值互动",
}

# 可查询的表及字段
AVAILABLE_TABLES = {
    "dws_customer_360": {
        "description": "客户360度视图（主表）",
        "fields": CUSTOMER_360_FIELDS,
    },
    "dws_contact_360": {
        "description": "联系人360度视图",
        "fields": CONTACT_360_FIELDS,
    },
    "dws_contact_mapping": {
        "description": "联系人跨系统映射表",
        "fields": CONTACT_MAPPING_FIELDS,
    },
    "dws_interaction_detail": {
        "description": "互动明细表",
        "fields": INTERACTION_DETAIL_FIELDS,
    },
}


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
    识别用户意图并提取结构化查询条件
    
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
    
    # 构建可用的字段说明
    fields_description = []
    for table_name, table_info in AVAILABLE_TABLES.items():
        fields_description.append(f"\n【{table_name}】({table_info['description']})")
        for field, desc in table_info["fields"].items():
            fields_description.append(f"  - {field}: {desc}")
    
    # 构建对话历史
    messages = [
        {
            "role": "system",
            "content": """你是一个智能客户查询助手。根据用户的问题，判断意图并提取结构化查询条件。

输出格式必须是 JSON，包含以下字段：
- "intent": 意图类型，只能是 "business_query"（业务查询）、"simple_question"（简单问题）或 "other"（其他）
- "structured_query": 如果是业务查询，包含结构化的查询条件；否则为空对象
- "target_table": 查询的目标表（如果有），可以是 "dws_customer_360"、"dws_contact_360"、"dws_contact_mapping"、"dws_interaction_detail" 或 "auto"（自动选择）
- "confidence": 对提取条件的置信度（0-1之间的小数）

## 可查询的数据库表及字段：

{fields}

## 实体提取规则：

1. 客户公司名称相关：
   - 如果用户明确说"名称是XXX"、"名称为XXX"、"叫XXX"，提取到 "customer_name"（精确匹配）
   - 如果用户说"名称包含XXX"、"名字里有XXX"、"名称类似XXX"、"名称含有XXX"，提取到 "keyword"（模糊匹配）
   - 如果用户只说"查询XXX公司"，提取到 "customer_name"（精确匹配）
   
2. 公司类型：
   - 固定为 "企业"（用户提到"企业"、"公司"等，不需要提取）

3. 地域：
   - 提取到 "region"（如 "北京"、"广东"、"上海"）

4. 公司拥有者名称/负责人：
   - 提取到 "owner_name"
   - 同义词：负责人、拥有者、owner、客户经理、跟进人、负责人姓名
   - 示例："负责人是张三" → 提取 "owner_name": "张三"

5. 所属行业：
   - 提取到 "industry"（如 "医疗"、"教育"、"金融"、"企业彩光ICT"）

6. 发展阶段/采购阶段：
   - 提取到 "purchase_stage"，必须是数据库中的完整值，不能自己造词！
   - 数据库 dws_customer_360 表中 purchase_stage 的完整枚举值如下：
        · "阶段0：未接触上客户"
        · "阶段1：接触上客户，初步交流"
        · "阶段2：正式交流，价值认可"
        · "阶段3：测试/入围，愿意尝试"
        · "阶段4：拿到门票，进入招投标"
        · "阶段5：已中标，等待采购"
        · "阶段6：完成采购，实现进入"
   - 映射规则（用户输入 → 数据库值），只要用户输入包含右侧关键词即匹配：
        · 含"未接触" → "阶段0：未接触上客户"
        · 含"初步交流"/"接触"/"解决方案探索" → "阶段1：接触上客户，初步交流"
        · 含"正式交流"/"价值认可" → "阶段2：正式交流，价值认可"
        · 含"测试"/"入围"/"尝试" → "阶段3：测试/入围，愿意尝试"
        · 含"招投标"/"拿门票" → "阶段4：拿到门票，进入招投标"
        · 含"中标" → "阶段5：已中标，等待采购"
        · 含"完成采购"/"进入" → "阶段6：完成采购，实现进入"
   - 如果用户说"XX及以上阶段"，则提取满足条件及以上所有阶段（输出为列表）
   - 示例："测试入围尝试" → 提取 "purchase_stage": "阶段3：测试/入围，愿意尝试"

7. 商机：
   - 提取到 "active_opp_count"（商机数量）或 "active_opp_amount"（商机金额）
   - 高/中/低商机：可以结合 intent_level 或 forecast_type

8. 人员覆盖度：
   - 提取到 "role_coverage"（如 "完整"、"部分"、"无"）

9. 意向等级：
   - 提取到 "intent_level"（如 "高"、"中"、"低"）
   - 也可以提取 "intent_score"（0-100的数值）

10. 近30天互动次数：
    - 提取到 "interaction_count_30d"（整数，可以提取最小值如 "互动次数大于5"）
    - 也可以提取 "interaction_min"（最小互动次数）

11. 最近一次交互时间：
    - 提取到 "last_interaction_time"（时间范围，如 "最近7天"、"本月"）
    - 可以转换为具体的时间条件

12. 公司联系人总数：
    - 提取到 "contact_count"（整数，可以提取最小值）

13. 联系人相关查询：
    - 如果查询联系人的姓名、手机号、邮箱等，设置 "target_table": "dws_contact_360" 或 "dws_contact_mapping"

14. 互动行为相关查询：
    - 如果查询具体的互动行为、渠道、内容等，设置 "target_table": "dws_interaction_detail"

15. 互动渠道（channel）—— 必须映射为数据库标准值：
    - 提取到 "channel"（互动渠道字段，在 dws_interaction_detail 表中）
    - ⚠️ 数据库中 channel 字段只有以下 4 种标准值，输出时必须使用英文标准值：
        · "email"   — 邮件/邮箱相关互动
        · "web"     — 官网/网站/网页/Web 渠道互动
        · "wechat"  — 微信/QQ/钉钉/IM 等社交软件互动
        · "event"   — 线下活动/展会/沙龙/研讨会等线下活动互动
    - 同义词 → 标准值 映射表（必须严格按此映射）：
        · email 同义词："邮件"、"邮箱"、"email"、"E-mail"、"e-mail"、"Email"、"EMAIL"
        · web 同义词："官网"、"网站"、"网页"、"Web"、"WEB"、"web"、"网页端"、"线上官网"、"互联网"
        · wechat 同义词："微信"、"QQ"、"钉钉"、"im"、"IM"、"聊天"、"社交"、"即时通讯"、"企微"、"企业微信"
        · event 同义词："活动"、"线下"、"展会"、"沙龙"、"研讨会"、"会议"、"峰会","路演"、"培训会"
    - 输出规则：无论用户用哪种说法，structured_query 中的 channel 必须是上述 4 个英文标准值之一
    - 示例：
        · "官网渠道有互动" → {{"channel": "web"}}
        · "邮箱互动了" → {{"channel": "email"}}
        · "微信上聊过" → {{"channel": "wechat"}}
        · "参加过活动" → {{"channel": "event"}}
    - 如果查询"有哪些公司有XX互动"，提取 channel 并设置 target_table 为 dws_interaction_detail

15b. 互动明细表的互动次数筛选（针对 dws_interaction_detail）：
    - 当用户说"XX渠道互动N次及以上"、"XX渠道互动超过N次"、"在XX渠道互动不少于N次"等时：
        · 提取 channel（按规则 15 映射为标准值）
        · 提取 "interaction_min"（整数，表示最低互动次数阈值）
    - 示例：
        · "官网渠道互动100次及以上" → {{"channel": "web", "interaction_min": 100}}
        · "邮件渠道互动超过50次" → {{"channel": "email", "interaction_min": 50}}
        · "微信渠道互动5次以上" → {{"channel": "wechat", "interaction_min": 5}}
    - 此类查询必须设置 "_distinct_customer": true 和 "target_table": "dws_interaction_detail"

16. 联系人姓名提取（中文尊称）：
    - 如果用户用"X经理"、"X总"、"X先生"、"X女士"、"X姐"、"X哥"等方式称呼某人，提取"X"作为 contact_name（模糊匹配）
    - 示例："胡经理的电话号码" → 提取 "contact_name": "胡"
    - 示例："李总的邮箱" → 提取 "contact_name": "李"
    - 示例："张先生的公司" → 提取 "contact_name": "张"
    - 如果明确说"姓名是XXX"、"叫XXX"，则完整提取（精确匹配）

17. 电话号码/手机号查询：
    - 如果用户询问"电话号码"、"手机号"、"手机"、"电话"、"联系方式"，这是查询 mobile 字段
    - 设置 target_table 为 "dws_contact_360"
    - 如果需要同时返回公司信息，设置 target_table 为 "dws_contact_mapping"

18. 聚合查询（计数类）：
    - 如果用户问"有多少家公司有XX"、"共有多少客户"等计数问题，仍按正常实体提取
    - SQL 生成阶段会根据查询类型自动处理计数逻辑

19. 时间范围查询（绝对时间，查询 dws_interaction_detail 表）：
    - 如果用户查询某个具体时间范围内的互动记录，提取 "event_time_start" 和 "event_time_end"
    - 日期格式必须标准化为 YYYY-MM-DD：
        · "2024年1月" → event_time_start: "2024-01-01", event_time_end: "2024-01-31"
        · "2024年1月15日" 或 "2024-01-15" → event_time_start: "2024-01-15", event_time_end: "2024-01-15"
        · "2024年1月到3月" / "2024年第一季度" → event_time_start: "2024-01-01", event_time_end: "2024-03-31"
        · "2024年上半年" → event_time_start: "2024-01-01", event_time_end: "2024-06-30"
    - 触发关键词："从X到Y期间"、"X到Y之间"、"X年以来"、"X年内"、"哪些公司在X时间段有互动"等
    - 如果提取到时间范围，设置 "target_table": "dws_interaction_detail"
    - 如果同时询问"哪些公司有互动"，还需添加 "_distinct_customer": true

## 示例：

示例输入1: "查找广东地区医疗行业高意向的客户"
示例输出1: {{"intent": "business_query", "structured_query": {{"industry": "医疗", "region": "广东", "intent_level": "高"}}, "target_table": "dws_customer_360", "confidence": 0.95}}

示例输入2: "帮我找北京的企业客户，意向等级是低，近30天互动次数是0"
示例输出2: {{"intent": "business_query", "structured_query": {{"region": "北京", "intent_level": "低", "interaction_count_30d": 0}}, "target_table": "dws_customer_360", "confidence": 0.9}}

示例输入3: "哪些客户的联系人总数超过10个"
示例输出3: {{"intent": "business_query", "structured_query": {{"contact_count_min": 10}}, "target_table": "dws_customer_360", "confidence": 0.85}}

示例输入4: "查找最近7天有互动的客户"
示例输出4: {{"intent": "business_query", "structured_query": {{"last_interaction_days": 7}}, "target_table": "dws_customer_360", "confidence": 0.9}}

示例输入5: "帮我看看这些客户的联系人都是谁"
示例输出5: {{"intent": "business_query", "structured_query": {{"query_type": "contacts"}}, "target_table": "dws_contact_360", "confidence": 0.8}}

示例输入6: "你好"
示例输出6: {{"intent": "simple_question", "structured_query": {{}}, "target_table": "", "confidence": 1.0}}

示例输入7: "今天天气怎么样"
示例输出7: {{"intent": "other", "structured_query": {{}}, "target_table": "", "confidence": 1.0}}

示例输入8: "帮我找北京的企业客户，负责人是张三"
示例输出8: {{"intent": "business_query", "structured_query": {{"region": "北京", "owner_name": "张三"}}, "target_table": "dws_customer_360", "confidence": 0.95}}

示例输入9: "查询名称包含测试的客户公司"
示例输出9: {{"intent": "business_query", "structured_query": {{"keyword": "测试"}}, "target_table": "dws_customer_360", "confidence": 0.9}}

示例输入10: "找负责人是李四的深圳客户"
示例输出10: {{"intent": "business_query", "structured_query": {{"region": "深圳", "owner_name": "李四"}}, "target_table": "dws_customer_360", "confidence": 0.9}}

示例输入11: "查询名字里有阿里巴巴的客户"
示例输出11: {{"intent": "business_query", "structured_query": {{"keyword": "阿里巴巴"}}, "target_table": "dws_customer_360", "confidence": 0.9}}

示例输入12: "哪些客户处于解决方案探索阶段？"
示例输出12: {{"intent": "business_query", "structured_query": {{"purchase_stage": "解决方案探索"}}, "target_table": "dws_customer_360", "confidence": 0.95}}

示例输入13: "查询处于需求构建阶段的客户"
示例输出13: {{"intent": "business_query", "structured_query": {{"purchase_stage": "需求构建"}}, "target_table": "dws_customer_360", "confidence": 0.95}}

示例输入14: "哪些客户处于交流及以上的阶段"
示例输出14: {{"intent": "business_query", "structured_query": {{"purchase_stage": ["阶段2：正式交流", "阶段3：方案评估", "阶段4：商务谈判", "阶段5：成交"]}}, "target_table": "dws_customer_360", "confidence": 0.9}}

示例输入15: "有哪些公司有email互动"
示例输出15: {{"intent": "business_query", "structured_query": {{"channel": "email"}}, "target_table": "dws_interaction_detail", "confidence": 0.9}}

示例输入16: "查询通过邮件互动的客户"
示例输出16: {{"intent": "business_query", "structured_query": {{"channel": "email"}}, "target_table": "dws_interaction_detail", "confidence": 0.9}}

示例输入17: "哪些客户有官网访问记录"
示例输出17: {{"intent": "business_query", "structured_query": {{"channel": "官网"}}, "target_table": "dws_interaction_detail", "confidence": 0.9}}

示例输入18: "胡经理的电话号码是多少"
示例输出18: {{"intent": "business_query", "structured_query": {{"contact_name": "胡"}}, "target_table": "dws_contact_360", "confidence": 0.9}}

示例输入19: "李总的邮箱是什么"
示例输出19: {{"intent": "business_query", "structured_query": {{"contact_name": "李"}}, "target_table": "dws_contact_360", "confidence": 0.9}}

示例输入20: "2024年1月到3月有哪些公司互动了"
示例输出20: {{"intent": "business_query", "structured_query": {{"event_time_start": "2024-01-01", "event_time_end": "2024-03-31", "_distinct_customer": true}}, "target_table": "dws_interaction_detail", "confidence": 0.95}}

示例输入21: "从2024-03-01到2024-03-15期间有哪些邮件互动"
示例输出21: {{"intent": "business_query", "structured_query": {{"event_time_start": "2024-03-01", "event_time_end": "2024-03-15", "channel": "email", "_distinct_customer": true}}, "target_table": "dws_interaction_detail", "confidence": 0.95}}

示例输入22: "2024年第一季度官网渠道有哪些互动记录"
示例输出22: {{"intent": "business_query", "structured_query": {{"event_time_start": "2024-01-01", "event_time_end": "2024-03-31", "channel": "web"}}, "target_table": "dws_interaction_detail", "confidence": 0.95}}

示例输入23: "官网渠道互动1次及以上"
示例输出23: {{"intent": "business_query", "structured_query": {{"channel": "web", "_distinct_customer": true, "interaction_min": 1}}, "target_table": "dws_interaction_detail", "confidence": 0.95}}

示例输入24: "通过邮件渠道有互动的公司"
示例输出24: {{"intent": "business_query", "structured_query": {{"channel": "email", "_distinct_customer": true}}, "target_table": "dws_interaction_detail", "confidence": 0.95}}

示例输入25: "官网渠道互动100次及以上"
示例输出25: {{"intent": "business_query", "structured_query": {{"channel": "web", "_distinct_customer": true, "interaction_min": 100}}, "target_table": "dws_interaction_detail", "confidence": 0.95}}

示例输入26: "微信渠道互动超过50次的公司有哪些"
示例输出26: {{"intent": "business_query", "structured_query": {{"channel": "wechat", "_distinct_customer": true, "interaction_min": 50}}, "target_table": "dws_interaction_detail", "confidence": 0.95}}

## 重要提示：
- 只输出 JSON，不要输出其他内容
- 如果提取到多个条件，都放在 structured_query 中
- 如果无法确定目标表，设置 "target_table": "auto"
- confidence 是对提取结果的置信度评估（0-1）
- 如果用户查询"有哪些公司有XX互动"、"哪些客户有XX互动"等，除了提取 channel 等条件外，还需要在 structured_query 中添加 "_distinct_customer": true，表示需要返回不重复的客户名称
""".format(fields="\n".join(fields_description)),
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
            max_tokens=800,
        )
        
        # 解析响应
        content = response.choices[0].message.content
        result = json.loads(content)
        
        # 验证结果格式
        if "intent" not in result:
            result["intent"] = "other"
        if "structured_query" not in result:
            result["structured_query"] = {}
        if "target_table" not in result:
            result["target_table"] = "auto"
        if "confidence" not in result:
            result["confidence"] = 0.5
        
        return result
        
    except Exception as e:
        logger.error("意图识别失败: %s", e)
        # 降级处理：默认为其他问题
        return {"intent": "other", "structured_query": {}, "target_table": "auto", "confidence": 0.0}


# ─────────────────────────────────────────────────────────────────────────────
# SQL 生成模块
# ─────────────────────────────────────────────────────────────────────────────

# 渠道名称 → 数据库标准值 映射表（兜底：AI 识别失败时自动转换）
_CHANNEL_MAP: Dict[str, str] = {
    # email 同义词
    "email": "email", "邮件": "email", "邮箱": "email",
    "e-mail": "email", "e_mail": "email", "E-mail": "email",
    "Email": "email", "EMAIL": "email", "E-MAIL": "email",
    # web 同义词
    "web": "web", "官网": "web", "网站": "web", "网页": "web",
    "WEB": "web", "Web": "web", "线上官网": "web", "网页端": "web",
    "互联网": "web", "website": "web",
    # wechat 同义词
    "wechat": "wechat", "微信": "wechat", "qq": "wechat", "QQ": "wechat",
    "钉钉": "wechat", "im": "wechat", "IM": "wechat", "聊天": "wechat",
    "社交": "wechat", "即时通讯": "wechat", "企微": "wechat",
    "企业微信": "wechat", "WeChat": "wechat",
    # event 同义词
    "event": "event", "活动": "event", "线下": "event",
    "展会": "event", "沙龙": "event", "研讨会": "event", "会议": "event",
    "峰会": "event", "路演": "event", "培训会": "event", "线下活动": "event",
}


def _normalize_channel(raw: str) -> str:
    """将用户/AI 返回的中文/英文渠道名统一映射为数据库标准值。"""
    raw_lower = raw.strip().lower()
    if raw_lower in _CHANNEL_MAP:
        return _CHANNEL_MAP[raw_lower]
    # 精确匹配未命中，尝试模糊包含
    for alias, std_val in _CHANNEL_MAP.items():
        if alias in raw or raw in alias:
            return std_val
    # 兜底：原值返回（可能是 AI 已经输出了正确标准值）
    return raw


def generate_sql(structured_query: Dict[str, Any], target_table: str = "dws_customer_360") -> Tuple[str, str, Dict[str, Any]]:
    """
    根据结构化查询生成 SQL
    
    不调用大模型，直接使用规则生成 SQL，提高响应速度。
    支持多表查询：dws_customer_360, dws_contact_360, dws_contact_mapping, dws_interaction_detail
    
    Args:
        structured_query: 结构化查询条件
        target_table: 目标表名
        
    Returns:
        (count_sql, data_sql, params): 计数SQL、数据SQL和参数
    """
    if not structured_query:
        return (
            f"SELECT COUNT(*) FROM {target_table} WHERE 1=1",
            f"SELECT * FROM {target_table} WHERE 1=1 LIMIT :limit OFFSET :offset",
            {}
        )
    
    # 检查是否需要返回不重复的客户名称（用于 dws_interaction_detail 表的查询）
    distinct_customer = structured_query.pop("_distinct_customer", False)
    
    # 提取 interaction_min（互动次数阈值），用于子查询 HAVING 过滤
    interaction_min = structured_query.pop("interaction_min", None)
    
    # 如果需要返回不重复的客户，且目标表是 dws_interaction_detail，
    # 则改为查询 dws_customer_360 表，使用子查询获取有互动的客户
    if distinct_customer and target_table == "dws_interaction_detail":
        # 生成子查询 SQL
        sub_where_parts = ["1=1"]
        sub_params = {}
        
        # 添加 dws_interaction_detail 的条件
        if "channel" in structured_query and structured_query["channel"]:
            raw_ch = structured_query["channel"]
            if isinstance(raw_ch, list):
                sub_where_parts.append("channel IN :channel")
                sub_params["channel"] = [_normalize_channel(c) for c in raw_ch]
            else:
                sub_where_parts.append("channel = :channel")
                sub_params["channel"] = _normalize_channel(raw_ch)
        
        if "behavior_type" in structured_query and structured_query["behavior_type"]:
            sub_where_parts.append("behavior_type LIKE :behavior_type")
            sub_params["behavior_type"] = f"%{structured_query['behavior_type']}%"
        
        if "content" in structured_query and structured_query["content"]:
            sub_where_parts.append("content LIKE :content")
            sub_params["content"] = f"%{structured_query['content']}%"
        
        if "last_interaction_days" in structured_query and structured_query["last_interaction_days"] is not None:
            sub_where_parts.append("event_time >= DATE_SUB(NOW(), INTERVAL :last_interaction_days DAY)")
            sub_params["last_interaction_days"] = structured_query["last_interaction_days"]

        # 绝对时间范围（子查询也需支持）
        if "event_time_start" in structured_query and structured_query["event_time_start"]:
            sub_where_parts.append("event_time >= :event_time_start")
            sub_params["event_time_start"] = structured_query["event_time_start"]

        if "event_time_end" in structured_query and structured_query["event_time_end"]:
            end_str = structured_query["event_time_end"]
            try:
                end_dt = datetime.strptime(end_str, "%Y-%m-%d") + timedelta(days=1)
                sub_params["event_time_end_exclusive"] = end_dt.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                sub_params["event_time_end_exclusive"] = end_str
            sub_where_parts.append("event_time < :event_time_end_exclusive")

        sub_where_sql = " AND ".join(sub_where_parts)
        
        # 修改目标表为 dws_customer_360
        target_table = "dws_customer_360"
        
        # 生成主查询 SQL（查询有互动的客户详情）
        where_parts = ["1=1"]
        params = {}
        
        # 构建子查询：有互动次数阈值时用 GROUP BY + HAVING，否则 DISTINCT
        if interaction_min is not None:
            sub_query = (
                f"SELECT customer_name FROM dws_interaction_detail "
                f"WHERE {sub_where_sql} "
                f"GROUP BY customer_name HAVING COUNT(*) >= :interaction_min"
            )
            params["interaction_min"] = int(interaction_min)
        else:
            sub_query = f"SELECT DISTINCT customer_name FROM dws_interaction_detail WHERE {sub_where_sql}"
        
        where_parts.append(f"customer_name IN ({sub_query})")
        params.update(sub_params)
    else:
        where_parts = ["1=1"]
        params = {}
    
    # 辅助函数：添加 WHERE 条件，支持单个值或列表值
    def _add_condition(sql_field: str, value: Any, param_key: Optional[str] = None, operator: str = "="):
        """
        添加 WHERE 条件，支持单个值（=）或列表值（IN）
        Args:
            sql_field: SQL 中的字段名
            value: 值（单个值或列表）
            param_key: 参数名（如果不指定，则使用 sql_field）
            operator: 操作符（仅对单个值有效，列表值始终使用 IN）
        """
        if param_key is None:
            param_key = sql_field
        if isinstance(value, list):
            # 列表值，使用 IN
            where_parts.append(f"{sql_field} IN :{param_key}")
            params[param_key] = value
        else:
            # 单个值
            if operator == "LIKE":
                where_parts.append(f"{sql_field} LIKE :{param_key}")
            else:
                where_parts.append(f"{sql_field} = :{param_key}")
            params[param_key] = value
    
    # ── dws_customer_360 字段处理 ──
    if target_table == "dws_customer_360":
        # 客户公司名称（优先使用模糊匹配，提高容错性）
        if "customer_name" in structured_query and structured_query["customer_name"]:
            # 如果值包含通配符或长度较短，使用模糊匹配；否则精确匹配
            cust_name = structured_query["customer_name"]
            if isinstance(cust_name, list):
                # 列表值，使用 IN
                where_parts.append("customer_name IN :customer_name")
                params["customer_name"] = cust_name
            elif len(cust_name) <= 4 or "%" in cust_name:
                where_parts.append("customer_name LIKE :customer_name")
                params["customer_name"] = f"%{cust_name}%"
            else:
                where_parts.append("customer_name = :customer_name")
                params["customer_name"] = cust_name
        
        # 关键词（模糊匹配客户名称）
        if "keyword" in structured_query and structured_query["keyword"]:
            keyword = structured_query["keyword"]
            if isinstance(keyword, list):
                # 多个关键词，使用 OR 连接
                keyword_conditions = []
                for i, kw in enumerate(keyword):
                    key = f"keyword_{i}"
                    keyword_conditions.append(f"customer_name LIKE :{key}")
                    params[key] = f"%{kw}%"
                where_parts.append("(" + " OR ".join(keyword_conditions) + ")")
            else:
                where_parts.append("customer_name LIKE :keyword")
                params["keyword"] = f"%{keyword}%"
        
        # 行业（支持列表）
        if "industry" in structured_query and structured_query["industry"]:
            _add_condition("industry", structured_query["industry"])
        
        # 地域/区域（支持列表）
        if "region" in structured_query and structured_query["region"]:
            _add_condition("region", structured_query["region"])
        
        # 公司拥有者名称/负责人（使用模糊匹配，提高容错性；支持列表）
        if "owner_name" in structured_query and structured_query["owner_name"]:
            owner_name = structured_query["owner_name"]
            if isinstance(owner_name, list):
                # 列表值，使用 OR 连接多个 LIKE 条件
                owner_conditions = []
                for i, name in enumerate(owner_name):
                    key = f"owner_name_{i}"
                    owner_conditions.append(f"owner_name LIKE :{key}")
                    params[key] = f"%{name}%"
                where_parts.append("(" + " OR ".join(owner_conditions) + ")")
            else:
                where_parts.append("owner_name LIKE :owner_name")
                params["owner_name"] = f"%{owner_name}%"
        
        # 发展阶段/采购阶段（支持列表）
        if "purchase_stage" in structured_query and structured_query["purchase_stage"]:
            _add_condition("purchase_stage", structured_query["purchase_stage"])
        
        # 预测类型（支持列表）
        if "forecast_type" in structured_query and structured_query["forecast_type"]:
            _add_condition("forecast_type", structured_query["forecast_type"])
        
        # 人员覆盖度（支持列表）
        if "role_coverage" in structured_query and structured_query["role_coverage"]:
            _add_condition("role_coverage", structured_query["role_coverage"])
        
        # 意向评分（不支持列表，为数值类型）
        if "intent_score" in structured_query and structured_query["intent_score"] is not None:
            where_parts.append("intent_score = :intent_score")
            params["intent_score"] = structured_query["intent_score"]
        
        # 意向等级（支持列表）
        if "intent_level" in structured_query and structured_query["intent_level"]:
            _add_condition("intent_level", structured_query["intent_level"])
        
        # 近30天互动次数（精确值）
        if "interaction_count_30d" in structured_query and structured_query["interaction_count_30d"] is not None:
            where_parts.append("interaction_count_30d = :interaction_count_30d")
            params["interaction_count_30d"] = structured_query["interaction_count_30d"]
        
        # 最小近30天互动次数
        if "interaction_min" in structured_query and structured_query["interaction_min"] is not None:
            where_parts.append("interaction_count_30d >= :interaction_min")
            params["interaction_min"] = structured_query["interaction_min"]
        
        # 总互动次数
        if "interaction_count_total" in structured_query and structured_query["interaction_count_total"] is not None:
            where_parts.append("interaction_count_total = :interaction_count_total")
            params["interaction_count_total"] = structured_query["interaction_count_total"]
        
        # 最近互动渠道（支持列表）
        if "channel" in structured_query and structured_query["channel"]:
            _add_condition("last_interaction_channel", structured_query["channel"], "channel")
        
        # 最近N天有互动
        if "last_interaction_days" in structured_query and structured_query["last_interaction_days"] is not None:
            where_parts.append("last_interaction_time >= DATE_SUB(NOW(), INTERVAL :last_interaction_days DAY)")
            params["last_interaction_days"] = structured_query["last_interaction_days"]
        
        # 活跃商机数量（精确值）
        if "active_opp_count" in structured_query and structured_query["active_opp_count"] is not None:
            where_parts.append("active_opp_count = :active_opp_count")
            params["active_opp_count"] = structured_query["active_opp_count"]
        
        # 活跃商机最小数量
        if "active_opp_count_min" in structured_query and structured_query["active_opp_count_min"] is not None:
            where_parts.append("active_opp_count >= :active_opp_count_min")
            params["active_opp_count_min"] = structured_query["active_opp_count_min"]
        
        # 活跃商机金额
        if "active_opp_amount" in structured_query and structured_query["active_opp_amount"] is not None:
            where_parts.append("active_opp_amount >= :active_opp_amount")
            params["active_opp_amount"] = structured_query["active_opp_amount"]
        
        # 公司联系人总数（精确值）
        if "contact_count" in structured_query and structured_query["contact_count"] is not None:
            where_parts.append("contact_count = :contact_count")
            params["contact_count"] = structured_query["contact_count"]
        
        # 公司联系人最小总数
        if "contact_count_min" in structured_query and structured_query["contact_count_min"] is not None:
            where_parts.append("contact_count >= :contact_count_min")
            params["contact_count_min"] = structured_query["contact_count_min"]
        
        # 是否现有客户
        if "is_existing_customer" in structured_query and structured_query["is_existing_customer"] is not None:
            where_parts.append("is_existing_customer = :is_existing_customer")
            params["is_existing_customer"] = structured_query["is_existing_customer"]
    
    # ── dws_contact_360 字段处理 ──
    elif target_table == "dws_contact_360":
        if "contact_name" in structured_query and structured_query["contact_name"]:
            where_parts.append("contact_name LIKE :contact_name")
            params["contact_name"] = f"%{structured_query['contact_name']}%"
        
        if "mobile" in structured_query and structured_query["mobile"]:
            where_parts.append("mobile = :mobile")
            params["mobile"] = structured_query["mobile"]
        
        if "email" in structured_query and structured_query["email"]:
            where_parts.append("email LIKE :email")
            params["email"] = f"%{structured_query['email']}%"
        
        if "department" in structured_query and structured_query["department"]:
            where_parts.append("department LIKE :department")
            params["department"] = f"%{structured_query['department']}%"
        
        if "position" in structured_query and structured_query["position"]:
            where_parts.append("position LIKE :position")
            params["position"] = f"%{structured_query['position']}%"
        
        if "role_category" in structured_query and structured_query["role_category"]:
            where_parts.append("role_category = :role_category")
            params["role_category"] = structured_query["role_category"]
        
        if "activity_level" in structured_query and structured_query["activity_level"]:
            where_parts.append("activity_level = :activity_level")
            params["activity_level"] = structured_query["activity_level"]
    
    # ── dws_contact_mapping 字段处理 ──
    elif target_table == "dws_contact_mapping":
        if "customer_name" in structured_query and structured_query["customer_name"]:
            where_parts.append("customer_name = :customer_name")
            params["customer_name"] = structured_query["customer_name"]
        
        if "contact_name" in structured_query and structured_query["contact_name"]:
            where_parts.append("contact_name LIKE :contact_name")
            params["contact_name"] = f"%{structured_query['contact_name']}%"
        
        if "mobile" in structured_query and structured_query["mobile"]:
            where_parts.append("mobile = :mobile")
            params["mobile"] = structured_query["mobile"]
        
        if "purchase_role" in structured_query and structured_query["purchase_role"]:
            where_parts.append("purchase_role = :purchase_role")
            params["purchase_role"] = structured_query["purchase_role"]
        
        if "role_category" in structured_query and structured_query["role_category"]:
            where_parts.append("role_category = :role_category")
            params["role_category"] = structured_query["role_category"]
    
    # ── dws_interaction_detail 字段处理 ──
    elif target_table == "dws_interaction_detail":
        if "customer_name" in structured_query and structured_query["customer_name"]:
            where_parts.append("customer_name = :customer_name")
            params["customer_name"] = structured_query["customer_name"]
        
        if "contact_name" in structured_query and structured_query["contact_name"]:
            where_parts.append("contact_name LIKE :contact_name")
            params["contact_name"] = f"%{structured_query['contact_name']}%"
        
        if "channel" in structured_query and structured_query["channel"]:
            # 将中文/别名映射为数据库标准值 (email/web/wechat/event)
            params["channel"] = _normalize_channel(structured_query["channel"])
            where_parts.append("channel = :channel")
        
        if "behavior_type" in structured_query and structured_query["behavior_type"]:
            where_parts.append("behavior_type LIKE :behavior_type")
            params["behavior_type"] = f"%{structured_query['behavior_type']}%"
        
        if "content" in structured_query and structured_query["content"]:
            where_parts.append("content LIKE :content")
            params["content"] = f"%{structured_query['content']}%"
        
        # 最近N天有互动
        if "last_interaction_days" in structured_query and structured_query["last_interaction_days"] is not None:
            where_parts.append("event_time >= DATE_SUB(NOW(), INTERVAL :last_interaction_days DAY)")
            params["last_interaction_days"] = structured_query["last_interaction_days"]

        # 绝对时间范围查询（event_time_start / event_time_end）
        if "event_time_start" in structured_query and structured_query["event_time_start"]:
            where_parts.append("event_time >= :event_time_start")
            params["event_time_start"] = structured_query["event_time_start"]

        if "event_time_end" in structured_query and structured_query["event_time_end"]:
            # 结束日期取次日 00:00:00，以包含结束日期当天全部数据
            end_str = structured_query["event_time_end"]
            try:
                end_dt = datetime.strptime(end_str, "%Y-%m-%d") + timedelta(days=1)
                params["event_time_end_exclusive"] = end_dt.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                params["event_time_end_exclusive"] = end_str
            where_parts.append("event_time < :event_time_end_exclusive")

        if "is_high_value" in structured_query and structured_query["is_high_value"] is not None:
            where_parts.append("is_high_value = :is_high_value")
            params["is_high_value"] = structured_query["is_high_value"]
    
    where_sql = " AND ".join(where_parts)
    
    # 生成正常查询 SQL
    count_sql = f"SELECT COUNT(*) FROM {target_table} WHERE {where_sql}"
    
    # 根据表选择默认排序
    if target_table == "dws_customer_360":
        data_sql = f"SELECT * FROM {target_table} WHERE {where_sql} ORDER BY intent_score DESC LIMIT :limit OFFSET :offset"
    elif target_table == "dws_interaction_detail":
        data_sql = f"SELECT * FROM {target_table} WHERE {where_sql} ORDER BY event_time DESC LIMIT :limit OFFSET :offset"
    else:
        data_sql = f"SELECT * FROM {target_table} WHERE {where_sql} LIMIT :limit OFFSET :offset"
    
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
    
    # 将 datetime、Decimal 等对象转换为可 JSON 序列化的类型
    items = []
    for row in rows:
        item = dict(row)
        # 遍历所有字段，转换特殊类型
        for key, value in item.items():
            if isinstance(value, Decimal):  # Decimal 类型转换为 float
                item[key] = float(value)
            elif hasattr(value, 'isoformat'):  # datetime 对象有 isoformat 方法
                item[key] = value.isoformat()
            elif hasattr(value, 'strftime'):  # date 对象有 strftime 方法
                item[key] = value.strftime('%Y-%m-%d %H:%M:%S')
        items.append(item)
    
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
                    structured_query: Dict[str, Any], target_table: str = "dws_customer_360",
                    db: Optional[Session] = None) -> str:
    """
    将 SQL 结果喂给大模型分析，生成前端回复
    
    优化说明：
    - 增加数据充足性判断
    - 明确告知用户哪些数据查到了，哪些没有
    - 支持多表查询结果分析
    
    Args:
        query: 用户原始查询
        sql_results: SQL 查询结果
        structured_query: 结构化查询条件
        target_table: 查询的目标表
        db: 数据库会话（用于补充查询）
        
    Returns:
        前端回复内容（包含导出功能提示）
    """
    if not sql_results:
        return f"系统错误：查询结果异常。"
    
    total = sql_results.get("total", 0)
    
    if total == 0:
        # 未找到结果，尝试提供建议
        suggestion = _generate_no_result_suggestion(structured_query, target_table)
        return f"未找到匹配的数据。{suggestion}"
    
    # 构建分析结果提示词
    items = sql_results["items"][:10]  # 只取前10条用于分析
    
    # 根据目标表简化结果数据
    simplified_items = []
    if target_table == "dws_customer_360":
        for item in items:
            simplified_items.append({
                "customer_name": item.get("customer_name", ""),
                "industry": item.get("industry", ""),
                "region": item.get("region", ""),
                "purchase_stage": item.get("purchase_stage", ""),
                "intent_level": item.get("intent_level", ""),
                "intent_score": item.get("intent_score", 0),
                "interaction_count_30d": item.get("interaction_count_30d", 0),
                "last_interaction_channel": item.get("last_interaction_channel", ""),
                "contact_count": item.get("contact_count", 0),
                "active_opp_count": item.get("active_opp_count", 0),
            })
    elif target_table == "dws_contact_360":
        for item in items:
            simplified_items.append({
                "contact_name": item.get("contact_name", ""),
                "mobile": item.get("mobile", ""),
                "department": item.get("department", ""),
                "position": item.get("position", ""),
                "role_category": item.get("role_category", ""),
                "interaction_count_30d": item.get("interaction_count_30d", 0),
            })
    elif target_table == "dws_contact_mapping":
        for item in items:
            simplified_items.append({
                "customer_name": item.get("customer_name", ""),
                "contact_name": item.get("contact_name", ""),
                "mobile": item.get("mobile", ""),
                "role_category": item.get("role_category", ""),
            })
    elif target_table == "dws_interaction_detail":
        for item in items:
            simplified_items.append({
                "customer_name": item.get("customer_name", ""),
                "contact_name": item.get("contact_name", ""),
                "channel": item.get("channel", ""),
                "behavior_type": item.get("behavior_type", ""),
                "content": item.get("content", ""),
                "event_time": str(item.get("event_time", "")),
            })
    
    # 检查数据充足性
    data_adequacy = _check_data_adequacy(query, structured_query, sql_results, target_table)
    
    # 构建数据来源信息
    table_names = {
        "dws_customer_360": "客户360视图",
        "dws_contact_360": "联系人360视图",
        "dws_contact_mapping": "联系人映射表",
        "dws_interaction_detail": "互动明细表",
    }
    table_display_name = table_names.get(target_table, target_table)
    
    # 构建查询字段列表
    field_descriptions = []
    if structured_query:
        for key in structured_query.keys():
            # 跳过内部使用的字段
            if key in ["query_type", "last_interaction_days", "interaction_min", 
                       "contact_count_min", "active_opp_count_min"]:
                continue
            # 获取字段的中文描述
            if target_table in AVAILABLE_TABLES and key in AVAILABLE_TABLES[target_table]["fields"]:
                field_descriptions.append(AVAILABLE_TABLES[target_table]["fields"][key])
            else:
                field_descriptions.append(key)
    
    query_fields = "、".join(field_descriptions) if field_descriptions else "全部字段"
    
    prompt = f"""
用户查询: {query}

查询条件: {json.dumps(structured_query, ensure_ascii=False)}

查询目标表: {target_table}（{table_display_name}）

查询结果: 共找到 {total} 条数据，以下是前 10 条：
{json.dumps(simplified_items, ensure_ascii=False, indent=2)}

数据充足性分析:
{data_adequacy}

请生成一段友好的回复，包含以下内容：
1. 简要总结查询结果（如数量、主要特征等）
2. 突出显示关键信息
3. 如果数据只有部分证据，明确说明哪些部分是查到的，哪些部分没查到可能有风险
4. 如果查不到某些数据，告诉用户没有这些数据，但可以帮他们查询哪些相关的数据
5. 建议下一步操作
6. 使用自然、专业的语气

【重要】在回复末尾，请务必添加一个"📚 数据来源"部分，格式如下：
📚 数据来源：
- 数据表：{table_display_name}（{target_table}）
- 查询字段：{query_fields}

回复要简洁明了，不超过300字。
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
                {"role": "system", "content": "你是一个专业的客户数据分析助手，擅长从数据中提取洞察、判断数据充足性，并给出建议。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=600,
        )
        
        analysis = response.choices[0].message.content or ""
        
        # 添加导出提示（仅对主表）
        if target_table == "dws_customer_360" and total > 0:
            export_hint = f'\n\n💡 提示：您可以点击"导出"按钮将全部 {total} 条结果导出为 Excel 文件。'
            return analysis + export_hint
        else:
            return analysis
        
    except Exception as e:
        logger.error("结果分析失败: %s", e)
        # 降级处理：返回简单结果
        return f'找到 {total} 条匹配的数据。您可以查看下方列表获取详细信息。'


def _check_data_adequacy(query: str, structured_query: Dict[str, Any], 
                         sql_results: Dict[str, Any], target_table: str) -> str:
    """
    检查数据充足性
    
    判断用户查询的问题是否都能从数据库中找到答案，
    明确告知哪些数据查到了，哪些没有。
    
    Args:
        query: 用户原始查询
        structured_query: 结构化查询条件
        sql_results: SQL 查询结果
        target_table: 查询的目标表
        
    Returns:
        数据充足性说明
    """
    adequacy_report = []
    
    # 检查查询条件是否都能在目标表中找到
    if structured_query:
        for key, value in structured_query.items():
            # 跳过内部使用的字段
            if key in ["query_type", "last_interaction_days", "interaction_min", 
                       "contact_count_min", "active_opp_count_min"]:
                continue
            
            # 检查字段是否在目标表的字段中
            if target_table in AVAILABLE_TABLES:
                if key not in AVAILABLE_TABLES[target_table]["fields"]:
                    adequacy_report.append(f"⚠️ 条件 '{key}' 不在表 {target_table} 的字段中，可能查询不准确")
    
    # 检查查询结果是否为空
    if sql_results.get("total", 0) == 0:
        adequacy_report.append("❌ 未找到匹配的数据")
    else:
        adequacy_report.append(f"✅ 找到 {sql_results['total']} 条匹配的数据")
    
    # 根据用户查询内容，检查是否需要关联其他表
    query_lower = query.lower()
    
    # 如果用户询问联系人相关信息，但查询的是客户表
    if target_table == "dws_customer_360":
        contact_keywords = ["联系人", "手机号", "邮箱", "决策人", "采购角色"]
        if any(kw in query for kw in contact_keywords):
            adequacy_report.append("💡 提示：您查询的内容可能涉及联系人信息，我可以帮您查询 dws_contact_360 或 dws_contact_mapping 表获取更详细的信息")
    
    # 如果用户询问互动行为，但查询的是客户表
    if target_table == "dws_customer_360":
        interaction_keywords = ["互动", "行为", "访问", "点击", "邮件", "直播"]
        if any(kw in query for kw in interaction_keywords):
            adequacy_report.append("💡 提示：您查询的内容可能涉及具体互动行为，我可以帮您查询 dws_interaction_detail 表获取详细的互动记录")
    
    if not adequacy_report:
        adequacy_report.append("✅ 数据充足，可以完整回答用户问题")
    
    return "\n".join(adequacy_report)


def _generate_no_result_suggestion(structured_query: Dict[str, Any], target_table: str) -> str:
    """
    生成无结果时的建议
    
    Args:
        structured_query: 结构化查询条件
        target_table: 查询的目标表
        
    Returns:
        建议文本
    """
    suggestions = []
    
    if target_table == "dws_customer_360":
        suggestions.append("建议：")
        suggestions.append("1. 尝试放宽查询条件（如去掉部分筛选条件）")
        suggestions.append("2. 检查行业、区域等字段的用词是否准确")
        suggestions.append("3. 尝试使用关键词模糊匹配（如输入部分公司名称）")
        
        if "industry" in structured_query:
            suggestions.append(f"   当前查询的行业：{structured_query['industry']}")
        if "region" in structured_query:
            suggestions.append(f"   当前查询的区域：{structured_query['region']}")
    
    return "\n".join(suggestions)


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
    2. 意图识别（包含实体提取和目标表选择）
    3. 根据意图分别处理：
       - business_query: 智能选择表 → 生成SQL → 查询数据库 → 分析结果
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
    target_table = intent_result.get("target_table", "auto")
    confidence = intent_result.get("confidence", 0.5)
    
    logger.info("意图识别结果: intent=%s, structured_query=%s, target_table=%s, confidence=%s", 
                intent, structured_query, target_table, confidence)
    
    # 3. 根据意图处理
    if intent == "business_query":
        # 业务查询：智能选择表 → 生成SQL → 查询数据库 → 分析结果
        if not db:
            return {
                "query": query,
                "preprocessed_query": preprocessed_query,
                "intent": intent,
                "structured_query": structured_query,
                "response": "系统错误：缺少数据库连接。",
                "customers": {"total": 0, "items": [], "page": 1, "page_size": 50},
            }
        
        # 智能选择目标表
        if target_table == "auto":
            target_table = _select_target_table(structured_query, query)
        
        logger.info("选择目标表: %s", target_table)
        
        # 生成SQL（传 copy 避免修改原 dict，保留 _distinct_customer 等内部字段）
        _sq = dict(structured_query)
        count_sql, data_sql, params = generate_sql(_sq, target_table)

        # ── 调试输出 ──
        print("=" * 60)
        print("[DEBUG] 目标表:", target_table)
        print("[DEBUG] 结构化查询条件:", json.dumps(structured_query, ensure_ascii=False))
        print("[DEBUG] count_sql:", count_sql)
        print("[DEBUG] data_sql:", data_sql)
        print("[DEBUG] SQL 参数:", params)
        print("=" * 60)

        # 执行查询
        # 对于非 dws_customer_360 表，返回全部数据以支持前端分页
        if target_table == "dws_customer_360":
            sql_results = execute_sql(db, count_sql, data_sql, params)
        else:
            # 其他表：获取全部数据（page_size 设为 10000）
            sql_results = execute_sql(db, count_sql, data_sql, params, page=1, page_size=10000)
        
        # ── 调试输出 ──
        print("[DEBUG] 查询结果: total=", sql_results.get("total", 0), ", items数量=", len(sql_results.get("items", [])))
        if sql_results.get("items"):
            print("[DEBUG] 第一条数据:", json.dumps(sql_results["items"][0], ensure_ascii=False))
        
        # 分析结果（传入目标表和数据库会话）
        response = analyze_results(query, sql_results, structured_query, target_table, db)
        
        # 根据目标表返回不同的结果格式
        if target_table == "dws_customer_360":
            return {
                "query": query,
                "preprocessed_query": preprocessed_query,
                "intent": intent,
                "structured_query": structured_query,
                "target_table": target_table,
                "response": response,
                "customers": sql_results,
            }
        else:
            # 其他表的结果放在 data 字段中
            return {
                "query": query,
                "preprocessed_query": preprocessed_query,
                "intent": intent,
                "structured_query": structured_query,
                "target_table": target_table,
                "response": response,
                "customers": {"total": 0, "items": [], "page": 1, "page_size": 50},
                "data": sql_results,  # 其他表的结果
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


def _select_target_table(structured_query: Dict[str, Any], query: str) -> str:
    """
    智能选择目标表
    
    根据查询条件和用户问题，自动选择最合适的表进行查询。
    
    Args:
        structured_query: 结构化查询条件
        query: 用户原始查询
        
    Returns:
        目标表名
    """
    query_lower = query.lower()
    
    # 1. 如果查询条件中包含 dws_interaction_detail 的字段，优先查询互动明细表
    interaction_fields = ["channel", "behavior_type", "content", "is_high_value", "event_time", "event_time_start", "event_time_end"]
    if any(field in structured_query for field in interaction_fields):
        return "dws_interaction_detail"
    
    # 2. 如果查询条件中包含联系人相关字段，查询联系人表
    contact_fields = ["contact_name", "mobile", "email", "department", "position", "purchase_role", "role_category"]
    if any(field in structured_query for field in contact_fields):
        # 判断是查询联系人360还是联系人映射表
        if "customer_id" in structured_query or "interaction_count" in query_lower:
            return "dws_contact_360"
        else:
            return "dws_contact_mapping"
    
    # 3. 如果用户询问具体的互动行为、渠道、内容等，查询互动明细表
    interaction_keywords = ["互动", "行为", "访问", "点击", "邮件", "直播", "活动", "渠道", "邮箱互动", "邮件互动", "官网访问", "web互动"]
    if any(kw in query for kw in interaction_keywords):
        return "dws_interaction_detail"
    
    # 4. 如果用户明确询问联系人信息
    contact_keywords = ["联系人", "手机号", "邮箱", "决策人", "采购角色", "部门", "职位", "电话", "手机", "电话号码", "联系方式"]
    if any(kw in query for kw in contact_keywords):
        return "dws_contact_360"
    
    # 5. 如果用户用"X经理"、"X总"等尊称询问某人信息
    honorific_pattern = r'\w+(经理|总|先生|女士|姐|哥)'
    if re.search(honorific_pattern, query):
        return "dws_contact_360"
    
    # 5. 默认查询客户360表
    return "dws_customer_360"


# ─────────────────────────────────────────────────────────────────────────────
# 导出功能
# ─────────────────────────────────────────────────────────────────────────────

def export_query_results(structured_query: Dict[str, Any], db: Session, 
                        target_table: str = "dws_customer_360") -> bytes:
    """
    导出查询结果为 Excel
    
    支持多表导出：dws_customer_360, dws_contact_360, dws_contact_mapping, dws_interaction_detail
    
    Args:
        structured_query: 结构化查询条件
        db: 数据库会话
        target_table: 目标表名
        
    Returns:
        Excel 文件的二进制数据
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
        import io
        from datetime import datetime
        
        # 传 copy 避免修改原 dict；根据 _distinct_customer 判断实际导出表
        _sq = dict(structured_query)
        _actual_table = (
            "dws_customer_360"
            if structured_query.get("_distinct_customer") and target_table == "dws_interaction_detail"
            else target_table
        )

        # 生成SQL（仅使用数据查询SQL，不需要计数SQL）
        _, data_sql, params = generate_sql(_sq, target_table)

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

        # 根据实际表定义导出列（注意：_actual_table 可能与 target_table 不同）
        if _actual_table == "dws_customer_360":
            columns = [
                ("customer_name", "客户名称", 25),
                ("industry", "行业", 15),
                ("region", "区域", 12),
                ("owner_name", "负责人", 15),
                ("purchase_stage", "采购阶段", 15),
                ("forecast_type", "预测类型", 12),
                ("role_coverage", "人员覆盖度", 12),
                ("intent_score", "意向评分", 12),
                ("intent_level", "意向等级", 12),
                ("interaction_count_30d", "近30天互动", 15),
                ("interaction_count_total", "总互动", 12),
                ("last_interaction_time", "最近互动时间", 20),
                ("last_interaction_channel", "最近渠道", 15),
                ("active_opp_count", "活跃商机数", 15),
                ("active_opp_amount", "活跃商机金额", 18),
                ("contact_count", "联系人总数", 15),
                ("mobile_count", "手机号数量", 15),
                ("is_existing_customer", "现有客户", 12),
            ]
        elif _actual_table == "dws_contact_360":
            columns = [
                ("customer_id", "客户ID", 12),
                ("contact_name", "联系人姓名", 20),
                ("mobile", "手机号", 15),
                ("email", "邮箱", 25),
                ("department", "部门", 20),
                ("position", "职位", 20),
                ("purchase_role", "采购角色", 15),
                ("role_category", "角色类别", 15),
                ("interaction_count", "总互动次数", 15),
                ("interaction_count_30d", "近30天互动", 15),
                ("last_interaction_time", "最近互动时间", 20),
                ("activity_level", "活跃度", 12),
                ("intent_level", "意向等级", 12),
                ("lead_stage", "线索阶段", 15),
            ]
        elif target_table == "dws_contact_mapping":
            columns = [
                ("customer_name", "客户公司", 25),
                ("contact_name", "联系人姓名", 20),
                ("mobile", "手机号", 15),
                ("email", "邮箱", 25),
                ("department", "部门", 20),
                ("position", "职位", 20),
                ("purchase_role", "采购角色", 15),
                ("role_category", "角色类别", 15),
                ("source_table", "来源表", 20),
                ("zhique_matched", "智能体匹配", 12),
            ]
        elif _actual_table == "dws_interaction_detail":
            columns = [
                ("customer_name", "客户公司", 25),
                ("contact_name", "联系人", 20),
                ("mobile", "手机号", 15),
                ("source_table", "来源表", 20),
                ("channel", "互动渠道", 15),
                ("behavior_type", "行为类型", 20),
                ("content", "互动内容", 50),
                ("event_time", "互动时间", 20),
                ("is_high_value", "高价值", 10),
            ]
        else:
            # 默认导出所有字段
            columns = [(key, key, 15) for key in items[0].keys()] if items else []
        
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
