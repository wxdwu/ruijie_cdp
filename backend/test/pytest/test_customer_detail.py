"""客户 360 详情接口测试：详情 / 联系人 / 互动 / 商机 / AI 洞察。

通过 mock_db 预设返回数据验证响应结构；不预设时（默认返回空）应返回 404。
"""
from fastapi.testclient import TestClient

from app.services.ai.contact_recommend import recommend_priority_contacts


CUSTOMER_ROW = {
    "id": 1,
    "customer_name": "测试客户A",
    "industry": "软件",
    "region": "广东",
    "owner_name": "张三",
    "contact_count": 5,
    "mobile_count": 3,
    "intent_level": "高",
    "intent_score": 82,
    "purchase_stage": "意向",
    "funnel_opp_count": 2,
    "last_interaction_time": None,
    "source_tables": "[]",
    "data_coverage": "[]",
}


def _seed_customer(mock_db):
    """所有详情类查询最终都依赖 `dws_customer_360 WHERE id`，此处统一预设。"""
    # _get_customer_name 仅取 customer_name 列并按位置 [0] 返回，需要更精确的匹配
    # 优先注册（匹配按注册顺序返回第一个命中项）。
    mock_db.add_result(
        "SELECT customer_name FROM dws_customer_360 WHERE id",
        rows=[{"customer_name": "测试客户A"}],
    )
    mock_db.add_result("dws_customer_360 WHERE id", rows=[dict(CUSTOMER_ROW)])


def test_detail_returns_200_and_fields(client, mock_db):
    _seed_customer(mock_db)
    r = client.get("/api/customers/1")
    assert r.status_code == 200
    body = r.json()
    assert body["customer_name"] == "测试客户A"
    assert body["industry"] == "软件"
    # 互动次数由独立 COUNT 子查询补充（mock 默认 0）
    assert "interaction_count_30d" in body
    assert body["interaction_count_30d"] == 0


def test_detail_missing_returns_404(client):
    r = client.get("/api/customers/999999")
    assert r.status_code == 404


def test_contacts_returns_envelope(client, mock_db):
    _seed_customer(mock_db)
    r = client.get("/api/customers/1/contacts")
    assert r.status_code == 200
    body = r.json()
    assert body["customer_id"] == "1"
    assert body["customer_name"] == "测试客户A"
    assert "contacts" in body and "total" in body
    assert isinstance(body["contacts"], list)


def test_contacts_missing_customer_404(client):
    r = client.get("/api/customers/999999/contacts")
    assert r.status_code == 404


def test_interactions_returns_envelope(client, mock_db):
    _seed_customer(mock_db)
    r = client.get("/api/customers/1/interactions", params={"limit": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["customer_name"] == "测试客户A"
    assert "interactions" in body and "total" in body


def test_interactions_missing_customer_404(client):
    r = client.get("/api/customers/999999/interactions")
    assert r.status_code == 404


def test_opportunities_returns_envelope(client, mock_db):
    _seed_customer(mock_db)
    r = client.get("/api/customers/1/opportunities")
    assert r.status_code == 200
    body = r.json()
    assert "opportunities" in body and "total" in body


def test_opportunities_missing_customer_404(client):
    r = client.get("/api/customers/999999/opportunities")
    assert r.status_code == 404


def test_ai_insight_returns_structure(client, mock_db):
    _seed_customer(mock_db)
    r = client.get("/api/customers/1/ai-insight")
    assert r.status_code == 200
    body = r.json()
    for key in ("business_conclusion", "evidence", "recommendation", "total_candidates"):
        assert key in body
    assert isinstance(body["business_conclusion"], list)
    assert isinstance(body["evidence"], dict)


def test_ai_insight_missing_customer_404(client):
    r = client.get("/api/customers/999999/ai-insight")
    assert r.status_code == 404


def test_recommend_priority_contacts_runs_with_mock(mock_db):
    """recommend_priority_contacts 在空数据下也应返回结构完整的字典。"""
    _seed_customer(mock_db)
    result = recommend_priority_contacts(
        db=mock_db, customer_id="1", customer_name="测试客户A", top_n=3
    )
    assert "recommendations" in result
    assert "total_candidates" in result
