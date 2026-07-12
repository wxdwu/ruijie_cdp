"""健康检查与基础路由测试。"""
from fastapi.testclient import TestClient


def test_health_ok(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "CDP ABM 360"


def test_unknown_route_returns_404(client: TestClient):
    r = client.get("/this/route/does/not/exist")
    assert r.status_code == 404
