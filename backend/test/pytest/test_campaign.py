"""营销活动分析接口测试（全部端点冒烟 + 过滤参数）。

campaign 服务仅做只读 SQL，不调用外部服务，默认 mock（空数据）即可返回信封。
"""
from fastapi.testclient import TestClient


ENDPOINTS = [
    "/api/campaign/filter-options",
    "/api/campaign/kpis",
    "/api/campaign/funnel-distribution",
    "/api/campaign/channel-distribution",
    "/api/campaign/role-coverage",
    "/api/campaign/stage-distribution",
    "/api/campaign/tag-signals",
    "/api/campaign/content-effect",
    "/api/campaign/customers-by-stage",
]


def test_all_campaign_endpoints_return_200(client: TestClient):
    for ep in ENDPOINTS:
        r = client.get(ep)
        assert r.status_code == 200, f"{ep} -> {r.status_code}: {r.text}"
        assert r.json()  # 返回 JSON 信封


def test_filter_options_keys(client: TestClient):
    r = client.get("/api/campaign/filter-options")
    body = r.json()
    for key in ("campaigns", "industries", "channels", "min_date", "max_date"):
        assert key in body


def test_kpis_keys(client: TestClient):
    r = client.get("/api/campaign/kpis")
    body = r.json()
    for key in ("total_customers", "active_customers", "opportunity_count", "total_amount"):
        assert key in body


def test_customers_by_stage_keys(client: TestClient):
    r = client.get("/api/campaign/customers-by-stage", params={"stage": "意向"})
    body = r.json()
    for key in ("grouped", "flat", "total", "page", "page_size", "total_pages"):
        assert key in body


def test_funnel_distribution_keys(client: TestClient):
    r = client.get("/api/campaign/funnel-distribution")
    body = r.json()
    for key in ("categories", "stages", "total"):
        assert key in body


def test_with_filters_does_not_error(client: TestClient):
    r = client.get(
        "/api/campaign/kpis",
        params={"campaign_tag": "C1", "start_date": "2026-01-01", "end_date": "2026-06-30", "channel": "邮件", "industry": "软件"},
    )
    assert r.status_code == 200
