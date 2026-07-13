"""客户列表接口测试：过滤条件生成、分页信封、响应结构。

同时覆盖 router 层与 service 层的 SQL 生成逻辑（与既有 test_customer_filters.py 风格一致）。
"""
from fastapi.testclient import TestClient

from app.routers.customer_list import list_customers


# ─────────────────────────────────────────────────────────────────────────────
# 直接调用 router 函数的辅助器
# ─────────────────────────────────────────────────────────────────────────────
# 直接调用 list_customers 时，FastAPI 的 Query(...) 默认值不会被解析，
# 因此必须显式传入全部参数，此处提供一个填充默认值的包装器。

def _call(mock_db, **overrides):
    kwargs = dict(
        keyword=None,
        special_project=None,
        industry=None,
        region=None,
        region_keyword=None,
        owner=None,
        owner_keyword=None,
        stage=None,
        intent_level=None,
        interaction_min=None,
        interaction_period=30,
        attribute=None,
        channel=None,
        sort=None,
        page=1,
        size=20,
    )
    kwargs.update(overrides)
    return list_customers(db=mock_db, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# 通过 HTTP 层验证响应信封
# ─────────────────────────────────────────────────────────────────────────────

def test_list_returns_200_and_envelope(client: TestClient):
    r = client.get("/api/customers", params={"page": 1, "size": 5})
    assert r.status_code == 200
    body = r.json()
    for key in ("items", "total", "filters_applied"):
        assert key in body
    assert isinstance(body["items"], list)


def test_list_pagination_params(client: TestClient):
    r = client.get(
        "/api/customers",
        params={"page": 2, "size": 10, "keyword": "测试", "industry": "软件"},
    )
    assert r.status_code == 200
    body = r.json()
    # 分页参数会回显在 filters_applied 中
    assert body["filters_applied"]["keyword"] == "测试"
    assert body["filters_applied"]["industry"] == "软件"


# ─────────────────────────────────────────────────────────────────────────────
# 直接调用 router 函数，断言生成的 SQL 与绑定参数（无需真实数据库）
# ─────────────────────────────────────────────────────────────────────────────

def test_keyword_filter_generates_like(mock_db):
    _call(mock_db, keyword="华为")
    sql, params = mock_db.calls[0]
    assert "customer_name LIKE :keyword" in sql
    assert params["keyword"] == "%华为%"


def test_standard_special_project_keeps_customer_360_source(mock_db):
    _call(mock_db, special_project="企业彩光ICT")
    sql, params = mock_db.calls[0]
    assert "dws_customer_360" in sql
    assert "campaign_tag = :special_project" in sql
    assert params["special_project"] == "企业彩光ICT"


def test_std_region_filter_uses_equal_condition(mock_db):
    _call(mock_db, region="广东")
    sql, params = mock_db.calls[0]
    assert "region = :region" in sql
    assert params["region"] == "广东"


def test_other_region_groups_non_standard_values(mock_db):
    _call(mock_db, region="其他")
    sql, params = mock_db.calls[0]
    assert "region IS NULL" in sql
    assert "region = ''" in sql
    assert "region NOT IN" in sql
    assert "region" not in params  # 实际参数名为 standard_region_0


def test_region_keyword_uses_like(mock_db):
    _call(mock_db, region_keyword="广")
    sql, params = mock_db.calls[0]
    assert "region LIKE :region_keyword" in sql
    assert params["region_keyword"] == "%广%"


def test_heavy_attribute_filter(mock_db):
    _call(mock_db, attribute="heavy")
    sql, params = mock_db.calls[0]
    assert "attribute = :heavy_attribute" in sql
    assert params["heavy_attribute"] == "H"


def test_non_heavy_attribute_filter(mock_db):
    _call(mock_db, attribute="non_heavy")
    sql, params = mock_db.calls[0]
    assert "(attribute IS NULL OR attribute != :heavy_attribute)" in sql
    assert params["heavy_attribute"] == "H"


def test_positive_interaction_min_uses_subquery(mock_db):
    _call(mock_db, interaction_min=3, interaction_period=30)
    sql, _ = mock_db.calls[0]
    assert "dws_interaction_detail" in sql
    assert "HAVING COUNT(*) >= :interaction_min" in sql


def test_zero_interaction_min_skips_subquery(mock_db):
    _call(mock_db, interaction_min=0)
    sql, params = mock_db.calls[0]
    assert "dws_interaction_detail" not in sql
    assert "interaction_min" not in params


def test_owner_keyword_uses_like(mock_db):
    _call(mock_db, owner_keyword="张")
    sql, params = mock_db.calls[0]
    assert "owner_name LIKE :owner_keyword" in sql
    assert params["owner_keyword"] == "%张%"


# ─────────────────────────────────────────────────────────────────────────────
# 重客专项：切换数据源并保持客户列表响应结构
# ─────────────────────────────────────────────────────────────────────────────

def test_key_account_filter_uses_latest_snapshot_and_maps_fields(mock_db):
    mock_db.add_result(
        "SELECT COUNT(*) FROM ods_crm_key_account_output_list_day",
        scalar=257,
    )
    mock_db.add_result(
        "`重客编码` AS id",
        rows=[{
            "id": "KH-001",
            "customer_name": "测试重客集团",
            "campaign_tag": "重客",
            "industry": None,
            "purchase_stage": None,
            "role_coverage": None,
            "intent_score": None,
            "intent_level": None,
            "interaction_count_total": None,
            "last_interaction_time": None,
            "last_interaction_channel": None,
        }],
    )

    result = _call(mock_db, special_project="重客")

    assert result["total"] == 257
    assert result["items"][0]["id"] == "KH-001"
    assert result["items"][0]["customer_name"] == "测试重客集团"
    assert result["items"][0]["campaign_tag"] == "重客"
    assert result["items"][0]["purchase_stage"] is None
    count_sql, _ = mock_db.calls[0]
    data_sql, _ = mock_db.calls[1]
    assert "ods_crm_key_account_output_list_day" in count_sql
    assert "MAX(`time`)" in count_sql
    assert "ORDER BY `重客名称` ASC, `重客编码` ASC" in data_sql


def test_key_account_filter_supports_keyword_and_pagination(mock_db):
    _call(
        mock_db,
        special_project="重客",
        keyword="中煤",
        page=2,
        size=20,
    )

    count_sql, count_params = mock_db.calls[0]
    _, data_params = mock_db.calls[1]
    assert "`重客名称` LIKE :keyword" in count_sql
    assert count_params == {"keyword": "%中煤%"}
    assert data_params["keyword"] == "%中煤%"
    assert data_params["limit"] == 20
    assert data_params["offset"] == 20


def test_key_account_filter_ignores_inapplicable_filters(mock_db):
    result = _call(
        mock_db,
        special_project="重客",
        industry="软件",
        region="广东",
        owner="张三",
        interaction_min=3,
        attribute="heavy",
        channel="email",
    )

    count_sql, count_params = mock_db.calls[0]
    _, data_params = mock_db.calls[1]
    assert "dws_customer_360" not in count_sql
    assert "dws_interaction_detail" not in count_sql
    assert count_params == {}
    assert data_params == {"limit": 20, "offset": 0}
    assert result["filters_applied"]["industry"] is None
    assert result["filters_applied"]["attribute"] is None
