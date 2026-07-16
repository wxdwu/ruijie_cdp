"""去重审核队列接口测试。

- 列表 / 统计：默认 mock 返回 0 / 空，断言信封结构。
- 通过 / 拒绝：预设审核项行并 mock 实际合并逻辑，断言成功返回。
- 边界：缺少审核项 -> 404；空 ID 列表 -> 400。
"""
from fastapi.testclient import TestClient

REVIEW_ROW = {
    "id": 7,
    "candidate_a_id": "A1",
    "candidate_a_name": "华为技术有限公司",
    "candidate_b_id": "B1",
    "candidate_b_name": "华为投资控股有限公司",
    "match_score": 0.92,
    "rule_score": 0.9,
    "evidence_score": 0.95,
    "llm_score": 0.91,
    "status": "pending",
    "evidence": "{}",
    "reviewed_by": None,
    "reviewed_at": None,
}


def test_list_returns_envelope(client: TestClient, mock_db):
    r = client.get("/api/review", params={"page": 1, "size": 20})
    assert r.status_code == 200
    body = r.json()
    for key in ("total", "items", "page", "size"):
        assert key in body


def test_list_with_seeded_item(client: TestClient, mock_db):
    mock_db.add_result("SELECT * FROM review_candidate", rows=[dict(REVIEW_ROW)])
    r = client.get("/api/review")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["items"], list)
    assert body["items"][0]["candidate_a_name"] == "华为技术有限公司"


def test_stats_returns_envelope(client: TestClient):
    r = client.get("/api/review/stats")
    assert r.status_code == 200
    body = r.json()
    for key in ("pending", "auto_merged", "rejected", "need_review", "total"):
        assert key in body


def test_approve_missing_returns_404(client):
    r = client.post("/api/review/12345/approve")
    assert r.status_code == 404


def test_approve_success(client: TestClient, mock_db, monkeypatch):
    mock_db.add_result("SELECT * FROM review_candidate", rows=[dict(REVIEW_ROW)])
    monkeypatch.setattr(
        "app.services.company_dedup.company_dedup.merge_customer_records",
        lambda item, db: None,
    )
    r = client.post("/api/review/7/approve")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["status"] == "auto_merged"


def test_reject_missing_returns_404(client):
    r = client.post("/api/review/12345/reject")
    assert r.status_code == 404


def test_reject_success(client: TestClient, mock_db):
    mock_db.add_result("SELECT * FROM review_candidate", rows=[dict(REVIEW_ROW)])
    r = client.post("/api/review/7/reject")
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"


def test_batch_approve_empty_ids_400(client):
    r = client.post("/api/review/batch-approve", json={"ids": []})
    assert r.status_code == 400


def test_batch_reject_empty_ids_400(client):
    r = client.post("/api/review/batch-reject", json={"ids": []})
    assert r.status_code == 400


def test_batch_approve_runs(client: TestClient, mock_db, monkeypatch):
    mock_db.add_result("SELECT * FROM review_candidate", rows=[dict(REVIEW_ROW)])
    monkeypatch.setattr(
        "app.services.company_dedup.company_dedup.merge_customer_records",
        lambda item, db: None,
    )
    r = client.post("/api/review/batch-approve", json={"ids": [7]})
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_run_dedup(client, monkeypatch):
    monkeypatch.setattr(
        "app.services.company_dedup.company_dedup.start_deduplication",
        lambda: {"status": "started", "task_id": "abc"},
    )
    r = client.post("/api/review/run-dedup")
    assert r.status_code == 200
    assert r.json()["status"] == "started"
