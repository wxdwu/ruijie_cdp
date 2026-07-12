"""表数据量监控接口测试（使用 mock_db）。"""
from fastapi.testclient import TestClient


def test_monitor_latest(client: TestClient):
    r = client.get("/api/admin/monitor/latest")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "snapshot" in body


def test_monitor_history(client: TestClient):
    r = client.get("/api/admin/monitor/history", params={"limit": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "records" in body


def test_monitor_run(client: TestClient):
    r = client.post("/api/admin/monitor/run")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "count" in body
    assert isinstance(body["records"], list)
