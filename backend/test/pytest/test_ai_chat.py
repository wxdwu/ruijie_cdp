"""AI 对话接口测试（mock LLM 服务，避免真实调用 DeepSeek）。

- /api/ai/parse   -> recognize_intent
- /api/ai/chat    -> process_chat
- /api/ai/chat/export -> export_query_results（返回 Excel 字节）
"""
from fastapi.testclient import TestClient
from fastapi.responses import Response


def test_parse_empty_returns_empty_entities(client: TestClient):
    r = client.post("/api/ai/parse", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == ""
    assert body["entities"] == {}


def test_parse_with_query(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        "app.services.wasted.ai_service.recognize_intent",
        lambda q, history=None: {"structured_query": {"region": "广东"}, "intent": "region"},
    )
    r = client.post("/api/ai/parse", json={"query": "广东的客户"})
    assert r.status_code == 200
    body = r.json()
    assert body["entities"] == {"region": "广东"}
    assert body["intent"] == "region"


def test_chat_empty_returns_prompt(client: TestClient):
    r = client.post("/api/ai/chat", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == ""
    assert "response" in body


def test_chat_with_query(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        "app.services.wasted.ai_service.process_chat",
        lambda q, history=None, db=None: {
            "query": q,
            "structured_query": {},
            "response": "好的",
            "customers": {"total": 0, "items": [], "page": 1, "page_size": 50},
            "intent": "other",
            "preprocessed_query": q,
        },
    )
    r = client.post("/api/ai/chat", json={"query": "高意向客户"})
    assert r.status_code == 200
    body = r.json()
    for key in ("query", "entities", "response", "customers", "intent", "preprocessed_query"):
        assert key in body


def test_chat_export_returns_excel(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        "app.services.wasted.ai_service.export_query_results",
        lambda structured_query, db, target_table="dws_customer_360": b"fake-xlsx-bytes",
    )
    r = client.post(
        "/api/ai/chat/export",
        json={"query": "广东客户", "entities": {"region": "广东"}},
    )
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]


def test_chat_export_missing_entities_400(client: TestClient):
    # entities 为空且未提供 structured_query 时，应返回 400（业务校验）
    r = client.post("/api/ai/chat/export", json={"query": "广东客户", "entities": {}})
    assert r.status_code == 400
