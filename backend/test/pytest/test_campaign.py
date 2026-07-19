"""营销活动分析接口测试（全部端点冒烟 + 过滤参数）。

campaign 服务仅做只读 SQL，不调用外部服务，默认 mock（空数据）即可返回信封。
"""
from datetime import date

from fastapi.testclient import TestClient

from app.services.campaign.campaign_service import (
    _campaign_filters,
    _customer_scope_sql,
    _interaction_filters,
    get_channel_distribution,
)


ENDPOINTS = [
    "/api/campaign/filter-options",
    "/api/campaign/bootstrap",
    "/api/campaign/overview",
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


def test_filter_options_group_raw_channels_like_attribution(client: TestClient, mock_db):
    mock_db.add_result(
        "AS channel FROM dws_interaction_detail i",
        rows=[
            {"channel": "other"},
            {"channel": "wechat"},
            {"channel": "email"},
            {"channel": "web"},
            {"channel": "event"},
        ],
    )

    body = client.get("/api/campaign/filter-options").json()
    channel_sql, channel_params = mock_db.calls[1]

    assert body["channels"] == ["email", "web", "event", "wechat", "other"]
    assert "ELSE 'other' END" in channel_sql
    assert "GROUP BY CASE" in channel_sql
    assert set(channel_params.values()) == {
        "email", "邮件", "web", "官网", "event", "直播/活动", "wechat", "微信",
    }


def test_filter_options_append_key_account_campaign_once(client: TestClient, mock_db):
    mock_db.add_result(
        "SELECT 'campaign' AS option_type",
        rows=[
            {"option_type": "campaign", "option_value": "企业彩光ICT"},
            {"option_type": "campaign", "option_value": "重客"},
            {"option_type": "industry", "option_value": "制造业"},
        ],
    )

    body = client.get("/api/campaign/filter-options").json()

    assert body["campaigns"] == ["企业彩光ICT", "重客"]
    assert body["campaigns"].count("重客") == 1


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


def test_overview_keys(client: TestClient):
    body = client.get("/api/campaign/overview").json()
    for key in (
        "kpis",
        "opportunity_distribution",
        "channel_distribution",
        "stage_distribution",
        "role_coverage",
        "tag_signals",
        "content_effect",
        "customer_filter_options",
    ):
        assert key in body


def test_bootstrap_keys(client: TestClient):
    body = client.get("/api/campaign/bootstrap").json()
    assert set(("filter_options", "applied_filters", "overview", "customers")) <= body.keys()


def test_overview_aggregates_rows_and_preserves_envelopes(client: TestClient, mock_db):
    mock_db.add_result(
        "SELECT 'kpi_total' AS section",
        rows=[
            {"section": "kpi_total", "label": "", "count_value": 2, "active_value": 0, "deal_value": 0, "unknown_value": 0, "amount_value": 0},
            {"section": "kpi_active", "label": "", "count_value": 1, "active_value": 0, "deal_value": 0, "unknown_value": 0, "amount_value": 0},
            {"section": "kpi_metrics", "label": "", "count_value": 3, "active_value": 0, "deal_value": 1, "unknown_value": 0, "amount_value": 1200},
            {"section": "opportunity", "label": "机会+", "count_value": 2, "active_value": 1, "deal_value": 1, "unknown_value": 0, "amount_value": 0},
            {"section": "channel", "label": "email", "count_value": 2, "active_value": 0, "deal_value": 0, "unknown_value": 0, "amount_value": 0},
            {"section": "stage", "label": "阶段1", "count_value": 2, "active_value": 0, "deal_value": 0, "unknown_value": 0, "amount_value": 0},
            {"section": "role", "label": "2/4", "count_value": 2, "active_value": 0, "deal_value": 0, "unknown_value": 0, "amount_value": 0},
            {"section": "signal", "label": "软件", "count_value": 2, "active_value": 0, "deal_value": 0, "unknown_value": 0, "amount_value": 0},
            {"section": "stage_option", "label": "阶段1", "count_value": 0, "active_value": 0, "deal_value": 0, "unknown_value": 0, "amount_value": 0},
            {"section": "owner_option", "label": "张三", "count_value": 0, "active_value": 0, "deal_value": 0, "unknown_value": 0, "amount_value": 0},
        ],
    )
    mock_db.add_result("i.content AS content", rows=[])

    body = client.get("/api/campaign/overview").json()
    assert body["kpis"] == {
        "total_customers": 2,
        "active_customers": 1,
        "opportunity_count": 3,
        "total_amount": 1200.0,
        "deal_customers": 1,
        "help_key": "campaign_kpis",
    }
    assert body["opportunity_distribution"]["categories"][0]["percentage"] == 100
    assert body["channel_distribution"]["channels"][0]["channel"] == "email"
    assert body["customer_filter_options"] == {"stages": ["阶段1"], "owners": ["张三"]}


def test_overview_can_defer_content_query(client: TestClient, mock_db):
    body = client.get(
        "/api/campaign/overview",
        params={"include_content": "false"},
    ).json()

    assert body["content_effect"] == {
        "data": [],
        "help_key": "content_effect",
        "deferred": True,
    }
    assert len(mock_db.calls) == 1


def test_content_effect_uses_compact_mysql_regex_aggregation(client: TestClient, mock_db):
    body = client.get("/api/campaign/content-effect").json()
    sql, _ = mock_db.calls[0]

    assert body == {"data": [], "help_key": "content_effect"}
    assert sql.count("REGEXP_LIKE") == 2
    assert "CONCAT_WS(' ', i.behavior_type, i.content) LIKE" not in sql


def test_time_filters_use_half_open_index_range():
    campaign_parts, campaign_params = _campaign_filters(
        start_date="2026-01-01",
        end_date="2026-06-30",
    )
    interaction_parts, interaction_params = _interaction_filters(
        start_date="2026-01-01",
        end_date="2026-06-30",
    )

    assert "DATE(" not in " ".join(campaign_parts + interaction_parts)
    assert "i.event_time >= :start_date" in campaign_parts[-1]
    assert "i.event_time < :end_exclusive" in campaign_parts[-1]
    assert interaction_params["end_exclusive"] == date(2026, 7, 1)
    assert campaign_params["end_exclusive"] == date(2026, 7, 1)


def test_key_account_scope_uses_latest_snapshot_and_source_project():
    scope_sql = _customer_scope_sql("重客")
    where_parts, params = _campaign_filters(
        campaign_tag="重客",
        channel="email",
        start_date="2026-07-01",
        end_date="2026-07-14",
        keyword="集团",
    )
    where_sql = " ".join(where_parts)

    assert "ods_crm_key_account_output_list_day" in scope_sql
    assert "MAX(`time`)" in scope_sql
    assert "GROUP BY `重客名称`" in scope_sql
    assert "LEFT JOIN dws_customer_360 c" in scope_sql
    assert "c.customer_name = ka.`重客名称`" in scope_sql
    assert "c.campaign_tag = :key_account_source_project" in scope_sql
    assert "COALESCE(c.customer_name, ka.`重客名称`) LIKE :keyword" in where_sql
    assert "i.customer_name = COALESCE(c.customer_name, ka.`重客名称`)" in where_sql
    assert params["key_account_source_project"] == "企业彩光ICT"
    assert params["keyword"] == "%集团%"


def test_key_account_overview_uses_shared_left_join_scope(client: TestClient, mock_db):
    client.get(
        "/api/campaign/overview",
        params={"campaign_tag": "重客", "include_content": "false"},
    )
    sql, params = mock_db.calls[0]

    assert "LEFT JOIN dws_customer_360 c" in sql
    assert "COUNT(DISTINCT COALESCE(c.customer_name, ka.`重客名称`))" in sql
    assert "COALESCE(NULLIF(c.purchase_stage, ''), '未知阶段')" in sql
    assert "COALESCE(NULLIF(c.role_coverage, ''), '0/4')" in sql
    assert params["key_account_source_project"] == "企业彩光ICT"


def test_key_account_customer_list_preserves_unmatched_snapshot_row(client: TestClient, mock_db):
    mock_db.add_result(
        "SELECT COUNT(DISTINCT COALESCE(c.customer_name, ka.`重客名称`))",
        scalar=1,
    )
    mock_db.add_result(
        "AS customer_name, '重客' AS campaign_tag",
        rows=[{
            "id": None,
            "customer_name": "尚未进入彩光的重客",
            "campaign_tag": "重客",
            "industry": None,
            "region": None,
            "attribute": None,
            "stage": None,
            "owner_name": None,
            "intent_level": None,
            "intent_score": None,
            "role_coverage": None,
            "last_interaction_time": None,
            "last_interaction_channel": None,
            "active_opp_amount": None,
            "active_opp_count": None,
            "interaction_count_total": None,
            "product_categories": None,
            "source_tables": None,
        }],
    )

    body = client.get(
        "/api/campaign/customers-by-stage",
        params={"campaign_tag": "重客", "include_filter_options": "false"},
    ).json()

    assert body["total"] == 1
    assert body["flat"][0]["id"] is None
    assert body["flat"][0]["customer_name"] == "尚未进入彩光的重客"
    assert body["flat"][0]["campaign_tag"] == "重客"
    assert body["flat"][0]["stage"] == "未知阶段"
    assert body["flat"][0]["active_opp_amount"] == 0


def test_key_account_content_effect_filters_interactions_by_latest_snapshot(client: TestClient, mock_db):
    client.get("/api/campaign/content-effect", params={"campaign_tag": "重客"})
    sql, params = mock_db.calls[0]

    assert "EXISTS (SELECT 1 FROM ods_crm_key_account_output_list_day ka" in sql
    assert "ka.`重客名称` = i.customer_name" in sql
    assert "MAX(`time`)" in sql
    assert "JOIN dws_customer_360 c ON c.customer_name = i.customer_name" not in sql
    assert params == {}


def test_key_account_bootstrap_keeps_campaign_option(client: TestClient):
    body = client.get("/api/campaign/bootstrap", params={"campaign_tag": "重客"}).json()

    assert body["applied_filters"]["campaign_tag"] == "重客"
    assert body["filter_options"]["campaigns"] == ["重客"]


def test_channel_filters_accept_canonical_categories_and_other_bucket():
    campaign_parts, campaign_params = _campaign_filters(channel="email")
    interaction_parts, interaction_params = _interaction_filters(channel="other")

    assert "i.channel IN" in " ".join(campaign_parts)
    assert set(campaign_params.values()) == {"email", "邮件"}
    interaction_sql = " ".join(interaction_parts)
    assert "i.channel NOT IN" in interaction_sql
    assert "i.channel IS NOT NULL" in interaction_sql
    assert set(interaction_params.values()) == {
        "email", "邮件", "web", "官网", "event", "直播/活动", "wechat", "微信",
    }


def test_customers_can_skip_filter_option_queries(client: TestClient, mock_db):
    body = client.get(
        "/api/campaign/customers-by-stage",
        params={"include_filter_options": "false"},
    ).json()
    assert "filter_options" not in body
    assert len(mock_db.calls) == 2


def test_channel_distribution_groups_unknown_values_as_other(mock_db):
    result = get_channel_distribution(db=mock_db)
    sql, params = mock_db.calls[0]
    assert "ELSE 'other' END" in sql
    assert "THEN '无渠道/未触达'" in sql
    assert "THEN 'email'" in sql
    assert set(params.values()) == {
        "email", "邮件", "web", "官网", "event", "直播/活动", "wechat", "微信",
    }
    assert result == {"channels": [], "total": 0, "help_key": "channel_attribution"}


def test_with_filters_does_not_error(client: TestClient):
    r = client.get(
        "/api/campaign/kpis",
        params={"campaign_tag": "C1", "start_date": "2026-01-01", "end_date": "2026-06-30", "channel": "邮件", "industry": "软件"},
    )
    assert r.status_code == 200
