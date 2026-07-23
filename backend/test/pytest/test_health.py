"""健康检查与基础路由测试。"""
from fastapi.testclient import TestClient


def test_health_ok(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "CDP ABM 360"
    assert body["cache"] == {"enabled": False, "status": "disabled"}


def test_health_stays_ok_when_cache_is_degraded(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        "app.main.get_cache_status",
        lambda: {"enabled": True, "status": "degraded"},
    )

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["cache"] == {"enabled": True, "status": "degraded"}


def test_unknown_route_returns_404(client: TestClient):
    r = client.get("/this/route/does/not/exist")
    assert r.status_code == 404
