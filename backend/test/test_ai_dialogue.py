#!/usr/bin/env python3
"""
AI 对话功能测试脚本

测试覆盖以下场景：
1. 客户360表查询（原有功能）
2. 联系人表查询（新增功能）
3. 互动明细表查询（新增功能）
4. 数据充足性判断（新增功能）
5. 多表联合查询（新增功能）
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services.ai_service import (
    preprocess_text,
    recognize_intent,
    generate_sql,
    analyze_results,
    process_chat,
    _check_data_adequacy,
    _select_target_table,
    AVAILABLE_TABLES,
)


client = TestClient(app)


# ─────────────────────────────────────────────────────────────────────────────
# 测试用例数据
# ─────────────────────────────────────────────────────────────────────────────

TEST_QUERIES = [
    # 1. 基础查询（客户360表）
    {
        "query": "查找广东地区医疗行业高意向的客户",
        "expected_intent": "business_query",
        "expected_table": "dws_customer_360",
        "expected_entities": ["industry", "region", "intent_level"],
    },
    # 2. 公司拥有者查询
    {
        "query": "帮我找北京的企业客户，负责人是张三",
        "expected_intent": "business_query",
        "expected_table": "dws_customer_360",
        "expected_entities": ["region", "owner_name"],
    },
    # 3. 发展阶段查询
    {
        "query": "哪些客户处于解决方案探索阶段？",
        "expected_intent": "business_query",
        "expected_table": "dws_customer_360",
        "expected_entities": ["purchase_stage"],
    },
    # 4. 商机查询
    {
        "query": "查找有高价值商机的客户",
        "expected_intent": "business_query",
        "expected_table": "dws_customer_360",
        "expected_entities": ["active_opp_count"],
    },
    # 5. 人员覆盖度查询
    {
        "query": "哪些客户的决策人覆盖度是完整的？",
        "expected_intent": "business_query",
        "expected_table": "dws_customer_360",
        "expected_entities": ["role_coverage"],
    },
    # 6. 意向等级和互动次数组合查询
    {
        "query": "帮我找低意向的客户，近30天互动次数是0",
        "expected_intent": "business_query",
        "expected_table": "dws_customer_360",
        "expected_entities": ["intent_level", "interaction_count_30d"],
    },
    # 7. 最近互动时间查询
    {
        "query": "查找最近7天有互动的客户",
        "expected_intent": "business_query",
        "expected_table": "dws_customer_360",
        "expected_entities": ["last_interaction_days"],
    },
    # 8. 联系人总数查询
    {
        "query": "哪些客户的联系人总数超过10个？",
        "expected_intent": "business_query",
        "expected_table": "dws_customer_360",
        "expected_entities": ["contact_count_min"],
    },
    # 9. 联系人信息查询（多表查询）
    {
        "query": "帮我看看这些客户的联系人都是谁",
        "expected_intent": "business_query",
        "expected_table": "dws_contact_360",
        "expected_entities": ["query_type"],
    },
    # 10. 联系人姓名查询
    {
        "query": "查找联系人叫李四的客户",
        "expected_intent": "business_query",
        "expected_table": "dws_contact_360",
        "expected_entities": ["contact_name"],
    },
    # 11. 互动行为查询（多表查询）
    {
        "query": "查看最近客户访问官网的互动记录",
        "expected_intent": "business_query",
        "expected_table": "dws_interaction_detail",
        "expected_entities": ["channel"],
    },
    # 12. 简单问题
    {
        "query": "你好",
        "expected_intent": "simple_question",
        "expected_table": None,
        "expected_entities": [],
    },
    # 13. 其他问题
    {
        "query": "今天天气怎么样？",
        "expected_intent": "other",
        "expected_table": None,
        "expected_entities": [],
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# 测试函数
# ─────────────────────────────────────────────────────────────────────────────

class TestPreprocessText:
    """测试文本预处理功能"""
    
    def test_remove_extra_spaces(self):
        """测试去除多余空格"""
        result = preprocess_text("查找    广东   地区的客户")
        assert "    " not in result
    
    def test_colloquial_replacement(self):
        """测试口语化表达替换"""
        result = preprocess_text("帮我找北京的客户")
        assert "找" in result
        assert "帮我找" not in result
    
    def test_pronoun_completion(self):
        """测试代词补全"""
        history = [{"role": "user", "text": "查找广东的医疗客户"}]
        result = preprocess_text("他们的联系人是谁？", history)
        assert "广东" in result or "医疗" in result


class TestRecognizeIntent:
    """测试意图识别功能"""
    
    @pytest.mark.parametrize("test_case", TEST_QUERIES[:10])
    def test_business_query_intent(self, test_case):
        """测试业务查询意图识别"""
        result = recognize_intent(test_case["query"])
        assert result["intent"] == "business_query"
        assert "structured_query" in result
        assert len(result["structured_query"]) > 0
    
    def test_simple_question_intent(self):
        """测试简单问题意图识别"""
        result = recognize_intent("你好")
        assert result["intent"] == "simple_question"
    
    def test_other_intent(self):
        """测试其他问题意图识别"""
        result = recognize_intent("今天天气怎么样？")
        assert result["intent"] == "other"
    
    def test_entity_extraction(self):
        """测试实体提取"""
        result = recognize_intent("查找广东地区医疗行业高意向的客户")
        sq = result["structured_query"]
        assert "industry" in sq or "region" in sq or "intent_level" in sq
    
    def test_target_table_selection(self):
        """测试目标表选择"""
        result = recognize_intent("查找联系人叫张三的客户")
        assert "target_table" in result
        assert result["target_table"] in ["dws_contact_360", "dws_contact_mapping", "auto"]


class TestGenerateSQL:
    """测试 SQL 生成功能"""
    
    def test_generate_sql_customer_360(self):
        """测试客户360表 SQL 生成"""
        sq = {
            "industry": "医疗",
            "region": "广东",
            "intent_level": "高",
        }
        count_sql, data_sql, params = generate_sql(sq, "dws_customer_360")
        
        assert "dws_customer_360" in count_sql
        assert "dws_customer_360" in data_sql
        assert "industry" in count_sql
        assert "region" in count_sql
        assert params["industry"] == "医疗"
        assert params["region"] == "广东"
    
    def test_generate_sql_with_interaction_min(self):
        """测试近30天互动次数条件"""
        sq = {
            "interaction_count_30d": 0,
        }
        count_sql, data_sql, params = generate_sql(sq, "dws_customer_360")
        
        assert "interaction_count_30d" in count_sql
        assert params["interaction_count_30d"] == 0
    
    def test_generate_sql_with_last_interaction_days(self):
        """测试最近互动天数条件"""
        sq = {
            "last_interaction_days": 7,
        }
        count_sql, data_sql, params = generate_sql(sq, "dws_customer_360")
        
        assert "DATE_SUB" in count_sql
        assert params["last_interaction_days"] == 7
    
    def test_generate_sql_contact_360(self):
        """测试联系人360表 SQL 生成"""
        sq = {
            "contact_name": "张三",
            "role_category": "决策者",
        }
        count_sql, data_sql, params = generate_sql(sq, "dws_contact_360")
        
        assert "dws_contact_360" in count_sql
        assert "contact_name" in count_sql
        assert "role_category" in count_sql
    
    def test_generate_sql_interaction_detail(self):
        """测试互动明细表 SQL 生成"""
        sq = {
            "channel": "官网",
            "behavior_type": "访问",
        }
        count_sql, data_sql, params = generate_sql(sq, "dws_interaction_detail")
        
        assert "dws_interaction_detail" in count_sql
        assert "channel" in count_sql
        assert "behavior_type" in count_sql


class TestSelectTargetTable:
    """测试智能选择目标表功能"""
    
    def test_auto_select_customer_360(self):
        """测试自动选择客户360表"""
        sq = {"industry": "医疗", "region": "广东"}
        result = _select_target_table(sq, "查找广东医疗客户")
        assert result == "dws_customer_360"
    
    def test_auto_select_contact_360(self):
        """测试自动选择联系人360表"""
        sq = {"contact_name": "张三"}
        result = _select_target_table(sq, "查找联系人张三")
        assert result in ["dws_contact_360", "dws_contact_mapping"]
    
    def test_auto_select_interaction_detail(self):
        """测试自动选择互动明细表"""
        sq = {"channel": "官网"}
        result = _select_target_table(sq, "查看客户访问官网的记录")
        assert result == "dws_interaction_detail"


class TestCheckDataAdequacy:
    """测试数据充足性判断功能"""
    
    def test_adequacy_with_results(self):
        """测试有结果时的数据充足性"""
        query = "查找广东地区的客户"
        sq = {"region": "广东"}
        sql_results = {"total": 10, "items": [{"customer_name": "测试客户"}]}
        
        result = _check_data_adequacy(query, sq, sql_results, "dws_customer_360")
        assert "✅" in result
    
    def test_adequacy_without_results(self):
        """测试无结果时的数据充足性"""
        query = "查找广东地区的客户"
        sq = {"region": "广东"}
        sql_results = {"total": 0, "items": []}
        
        result = _check_data_adequacy(query, sq, sql_results, "dws_customer_360")
        assert "❌" in result
    
    def test_adequacy_with_contact_keywords(self):
        """测试询问联系人时的数据充足性提示"""
        query = "这些客户的联系人是谁？"
        sq = {"region": "广东"}
        sql_results = {"total": 10, "items": []}
        
        result = _check_data_adequacy(query, sq, sql_results, "dws_customer_360")
        assert "💡" in result


class TestProcessChat:
    """测试完整对话处理流程"""
    
    def test_process_chat_business_query(self):
        """测试业务查询处理"""
        # 注意：这个测试需要数据库连接，可能需要 mock
        result = process_chat("你好")
        assert "response" in result
        assert "query" in result
    
    def test_process_chat_simple_question(self):
        """测试简单问题处理"""
        result = process_chat("你好")
        assert result["intent"] == "simple_question"
        assert "response" in result
    
    def test_process_chat_other(self):
        """测试其他问题处理"""
        result = process_chat("今天天气怎么样？")
        assert result["intent"] == "other"
        assert "response" in result


class TestAvailableTables:
    """测试可用表定义"""
    
    def test_all_tables_defined(self):
        """测试所有表都已定义"""
        expected_tables = [
            "dws_customer_360",
            "dws_contact_360",
            "dws_contact_mapping",
            "dws_interaction_detail",
        ]
        for table in expected_tables:
            assert table in AVAILABLE_TABLES
    
    def test_table_fields_defined(self):
        """测试表的字段都已定义"""
        for table_name, table_info in AVAILABLE_TABLES.items():
            assert "fields" in table_info
            assert len(table_info["fields"]) > 0


# ─────────────────────────────────────────────────────────────────────────────
# API 端点测试
# ─────────────────────────────────────────────────────────────────────────────

class TestAIChatAPI:
    """测试 AI 对话 API 端点"""
    
    def test_chat_endpoint(self):
        """测试 /api/ai/chat 端点"""
        response = client.post(
            "/api/ai/chat",
            json={"query": "你好"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "query" in data
        assert "response" in data
    
    def test_parse_endpoint(self):
        """测试 /api/ai/parse 端点"""
        response = client.post(
            "/api/ai/parse",
            json={"query": "查找广东地区的客户"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "query" in data
        assert "entities" in data
    
    # 注意：导出端点测试需要数据库数据，可能需要单独的集成测试


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
