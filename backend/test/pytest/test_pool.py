"""连接池管理接口测试（不依赖真实数据库）。

安全用例：status / config / stats 只读配置；非法熔断状态 -> 422；
warmup 超过 pool_size -> 400；reset 缺少确认 -> 400；带确认且 mock reset_pool -> 200。
"""
from fastapi.testclient import TestClient


def test_pool_status(client: TestClient):
    r = client.get("/api/pool/status")
    assert r.status_code == 200
    assert "pool_size" in r.json()


def test_pool_config(client: TestClient):
    r = client.get("/api/pool/config")
    assert r.status_code == 200
    assert "pool_size" in r.json()


def test_pool_stats(client: TestClient):
    r = client.get("/api/pool/stats")
    assert r.status_code == 200
    body = r.json()
    assert "retry_count" in body
    assert "config" in body


def test_circuit_breaker_invalid_state_422(client: TestClient):
    r = client.post("/api/pool/circuit-breaker/not_a_state")
    assert r.status_code == 422


def test_warmup_exceeds_pool_size_400(client: TestClient):
    r = client.post("/api/pool/warmup", params={"min_connections": 99999})
    assert r.status_code == 400


def test_reset_requires_confirm_400(client: TestClient):
    r = client.post("/api/pool/reset")
    assert r.status_code == 400


def test_reset_with_confirm(client: TestClient, monkeypatch):
    # reset_pool 在 pool 路由中以名字直接导入，需 patch 路由模块内的引用
    monkeypatch.setattr("app.routers.pool.reset_pool", lambda: {"status": "reset"})
    r = client.post("/api/pool/reset", params={"confirm": True})
    assert r.status_code == 200
    assert r.json()["status"] == "reset"
