"""ETL 同步接口测试（mock 引擎，避免真实 MySQL / 重同步）。

- /api/admin/etl/status、/history：mock get_etl_engine 返回可控结果。
- /api/admin/etl/full、/increment：mock run_full_sync / run_incremental_sync。
"""
from datetime import datetime

from fastapi.testclient import TestClient
from conftest import MockResult, Row


class _MockConn:
    def __init__(self, engine):
        self._engine = engine

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, statement, params=None):
        sql = str(statement)
        e = self._engine
        if "ORDER BY id DESC" in sql and "LIMIT 1" in sql:
            return MockResult(rows=[e._status_row], rowcount=0)
        if "COUNT(*)" in sql:
            # sync.py 通过 fetchone()[0] 取总数，需返回一行位置 0 为总数
            return MockResult(rows=[{0: e._total}], scalar=e._total, rowcount=0)
        return MockResult(rows=e._history_rows, rowcount=0)


class _MockEngine:
    def __init__(self, status_row, history_rows, total):
        self._status_row = status_row
        self._history_rows = history_rows
        self._total = total

    def connect(self):
        return _MockConn(self)


def _make_engine():
    status_row = {
        0: 1, 1: "full", 2: "system", 3: "success",
        4: datetime(2026, 7, 1, 10, 0, 0), 5: datetime(2026, 7, 1, 10, 5, 0),
        6: 300, 7: 1000, 8: None,
    }
    history_rows = [dict(status_row)]
    return _MockEngine(status_row, history_rows, total=1)


def test_etl_status(client: TestClient, monkeypatch):
    engine = _make_engine()
    monkeypatch.setattr("app.routers.sync.get_etl_engine", lambda: engine)
    r = client.get("/api/admin/etl/status")
    assert r.status_code == 200
    body = r.json()
    assert body["sync_id"] == 1
    assert body["sync_type"] == "full"
    assert body["status"] == "success"


def test_etl_history(client: TestClient, monkeypatch):
    engine = _make_engine()
    monkeypatch.setattr("app.routers.sync.get_etl_engine", lambda: engine)
    r = client.get("/api/admin/etl/history", params={"limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert isinstance(body["records"], list)
    assert body["records"][0]["sync_type"] == "full"


def test_etl_full_trigger(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        "app.routers.sync.run_full_sync",
        lambda trigger_by="system": {"log_id": 42, "elapsed_seconds": 1.5},
    )
    r = client.post("/api/admin/etl/full", params={"trigger_by": "tester"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["sync_id"] == 42


def test_etl_increment_trigger(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        "app.routers.sync.run_incremental_sync",
        lambda trigger_by="system": {"log_id": 43, "elapsed_seconds": 0.8},
    )
    r = client.post("/api/admin/etl/increment")
    assert r.status_code == 200
    assert r.json()["sync_id"] == 43
