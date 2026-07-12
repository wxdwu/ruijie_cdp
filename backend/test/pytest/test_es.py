"""ElasticSearch CRUD / 同步接口测试（mock ES 服务，避免真实 ES 集群）。

es_crud 路由通过 `app.services.es_crud.*` 调用，es_sync 路由通过
`app.services.es_sync.*` 调用；直接 patch 这些模块级函数即可。
"""
from fastapi.testclient import TestClient


# ─────────────────────────────────────────────────────────────────────────────
# ES CRUD
# ─────────────────────────────────────────────────────────────────────────────

def test_es_get_doc(client: TestClient, monkeypatch):
    monkeypatch.setattr("app.services.es_crud.es_get", lambda index, doc_id: {"name": "x"})
    r = client.get("/api/admin/es/cdp_customer_360/abc")
    assert r.status_code == 200
    assert r.json()["doc"] == {"name": "x"}


def test_es_get_doc_not_found_404(client: TestClient, monkeypatch):
    monkeypatch.setattr("app.services.es_crud.es_get", lambda index, doc_id: None)
    r = client.get("/api/admin/es/cdp_customer_360/abc")
    assert r.status_code == 404


def test_es_batch_create(client: TestClient, monkeypatch):
    monkeypatch.setattr("app.services.es_crud.es_bulk_create", lambda index, docs, batch_size: 3)
    r = client.post(
        "/api/admin/es/cdp_customer_360/batch-create",
        json={"docs": [{"id": 1}, {"id": 2}, {"id": 3}]},
    )
    assert r.status_code == 200
    assert r.json()["created"] == 3


def test_es_search(client: TestClient, monkeypatch):
    monkeypatch.setattr("app.services.es_crud.es_search", lambda index, query: {"hits": {}})
    r = client.post("/api/admin/es/cdp_customer_360/search", json={"query": {"match_all": {}}})
    assert r.status_code == 200
    assert r.json()["hits"] == {}


def test_es_update(client: TestClient, monkeypatch):
    monkeypatch.setattr("app.services.es_crud.es_update", lambda index, doc_id, doc: None)
    r = client.put("/api/admin/es/cdp_customer_360/abc", json={"name": "y"})
    assert r.status_code == 200
    assert r.json()["updated"] is True


def test_es_batch_update(client: TestClient, monkeypatch):
    monkeypatch.setattr("app.services.es_crud.es_bulk_update", lambda index, docs, batch_size: 2)
    r = client.post(
        "/api/admin/es/cdp_customer_360/batch-update",
        json={"docs": [{"id": 1}, {"id": 2}]},
    )
    assert r.status_code == 200
    assert r.json()["updated"] == 2


def test_es_delete(client: TestClient, monkeypatch):
    monkeypatch.setattr("app.services.es_crud.es_delete", lambda index, doc_id: True)
    r = client.delete("/api/admin/es/cdp_customer_360/abc")
    assert r.status_code == 200
    assert r.json()["deleted"] is True


def test_es_batch_delete(client: TestClient, monkeypatch):
    monkeypatch.setattr("app.services.es_crud.es_bulk_delete", lambda index, ids, batch_size: 2)
    r = client.post("/api/admin/es/cdp_customer_360/batch-delete", json={"ids": ["1", "2"]})
    assert r.status_code == 200
    assert r.json()["deleted"] == 2


def test_es_delete_by_query(client: TestClient, monkeypatch):
    monkeypatch.setattr("app.services.es_crud.es_delete_by_query", lambda index, query: 5)
    r = client.post(
        "/api/admin/es/cdp_customer_360/delete-by-query",
        json={"query": {"match_all": {}}},
    )
    assert r.status_code == 200
    assert r.json()["deleted"] == 5


# ─────────────────────────────────────────────────────────────────────────────
# ES 同步
# ─────────────────────────────────────────────────────────────────────────────

def test_es_full_sync(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        "app.services.es_sync.run_es_full_sync", lambda: {"synced": 100}
    )
    r = client.post("/api/admin/es/full", params={"trigger_by": "tester"})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_es_increment_sync(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        "app.services.es_sync.run_es_incremental_sync", lambda: {"synced": 10}
    )
    r = client.post("/api/admin/es/increment")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_es_health(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        "app.services.es_sync.get_es_health",
        lambda: {"status": "green", "indices": {}},
    )
    r = client.get("/api/admin/es/health")
    assert r.status_code == 200
    assert r.json()["status"] == "green"
