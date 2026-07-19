"""客户列表接口测试：过滤条件生成、分页信封、响应结构。

同时覆盖 router 层与 service 层的 SQL 生成逻辑（与既有 test_customer_filters.py 风格一致）。

专项/行业/区域/负责人/客户关键词/互动方式均为多选，对应后端 ``List[str]`` 参数，
测试中以列表形式传入（例如 ``region=["广东"]``、``keyword=["华为"]``、``channel=["email"]``）。
"""
from io import BytesIO

import openpyxl
from fastapi.testclient import TestClient

from app.routers.customer import get_filter_options, list_customers


# ─────────────────────────────────────────────────────────────────────────────
# 直接调用 router 函数的辅助器
# ─────────────────────────────────────────────────────────────────────────────
# 直接调用 list_customers 时，FastAPI 的 Query(...) 默认值不会被解析，
# 因此必须显式传入全部参数，此处提供一个填充默认值的包装器。
# 多选维度统一使用列表（与前端联动后的后端契约一致）。

def _call(mock_db, **overrides):
    kwargs = dict(
        keyword=None,
        special_project=[],
        industry=[],
        region=[],
        region_keyword=None,
        owner=[],
        owner_keyword=None,
        stage=None,
        intent_level=None,
        interaction_min=None,
        interaction_period=30,
        attribute=None,
        channel=[],
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
    assert body["filters_applied"]["keyword"] == ["测试"]
    # 多选维度回显为数组
    assert body["filters_applied"]["industry"] == ["软件"]


# ─────────────────────────────────────────────────────────────────────────────
# 直接调用 router 函数，断言生成的 SQL 与绑定参数（无需真实数据库）
# ─────────────────────────────────────────────────────────────────────────────

def test_keyword_filter_generates_in(mock_db):
    _call(mock_db, keyword=["华为"])
    sql, params = mock_db.calls[0]
    assert "customer_name IN (:keyword_0)" in sql
    assert params["keyword_0"] == "华为"


def test_standard_special_project_keeps_customer_360_source(mock_db):
    _call(mock_db, special_project=["企业彩光ICT"])
    sql, params = mock_db.calls[0]
    assert "dws_customer_360" in sql
    assert "campaign_tag IN (:special_project_0)" in sql
    assert params["special_project_0"] == "企业彩光ICT"


def test_standard_region_filter_matches_plain_and_area_suffix(mock_db):
    _call(mock_db, region=["广东"])
    sql, params = mock_db.calls[0]
    assert "region IN (:region_exact_0, :region_area_0)" in sql
    assert params["region_exact_0"] == "广东"
    assert params["region_area_0"] == "广东区域"


def test_other_region_groups_non_standard_values(mock_db):
    _call(mock_db, region=["其他"])
    sql, params = mock_db.calls[0]
    assert "region IS NULL" in sql
    assert "region = ''" in sql
    assert "region NOT IN" in sql
    assert "广东" in params.values()
    assert "广东区域" in params.values()


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


def test_canonical_channel_filter_accepts_code_and_chinese_label(mock_db):
    _call(mock_db, channel=["email"])
    sql, params = mock_db.calls[0]
    assert "EXISTS (SELECT 1 FROM dws_interaction_detail ic" in sql
    assert "ic.customer_name = dws_customer_360.customer_name" in sql
    assert "ic.channel IN" in sql
    assert set(params.values()) == {"email", "邮件"}


def test_other_channel_filter_excludes_known_and_empty_values(mock_db):
    _call(mock_db, channel=["other"])
    sql, params = mock_db.calls[0]
    assert "ic.channel IS NOT NULL" in sql
    assert "TRIM(ic.channel) != ''" in sql
    assert "ic.channel NOT IN" in sql
    assert set(params.values()) == {
        "email", "邮件", "web", "官网", "event", "直播/活动", "wechat", "微信",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 重客专项：切换数据源并保持客户列表响应结构
# ─────────────────────────────────────────────────────────────────────────────

def test_key_account_filter_uses_latest_snapshot_and_maps_fields(mock_db):
    mock_db.add_result(
        "SELECT COUNT(*)",
        scalar=257,
    )
    mock_db.add_result(
        "`重客编码` AS key_account_code",
        rows=[{
            "id": 42,
            "customer_name": "彩光侧名称",
            "campaign_tag": "企业彩光ICT",
            "industry": "制造业",
            "purchase_stage": "需求构建",
            "role_coverage": "部分",
            "intent_score": 88,
            "intent_level": "高",
            "interaction_count_total": 12,
            "last_interaction_time": "2026-07-13 10:00:00",
            "last_interaction_channel": "web",
            "key_account_code": "KH-001",
            "key_account_name": "测试重客集团",
        }],
    )

    result = _call(mock_db, special_project=["重客"])

    assert result["total"] == 257
    assert result["items"][0]["id"] == 42
    assert result["items"][0]["key_account_code"] == "KH-001"
    assert result["items"][0]["customer_name"] == "测试重客集团"
    assert result["items"][0]["campaign_tag"] == "重客"
    assert result["items"][0]["industry"] == "制造业"
    assert result["items"][0]["purchase_stage"] == "需求构建"
    assert result["filters_applied"]["attribute"] == "heavy"
    assert result["filters_applied"]["special_project"] == ["重客"]
    count_sql, _ = mock_db.calls[0]
    data_sql, _ = mock_db.calls[1]
    assert "ods_crm_key_account_output_list_day" in count_sql
    assert "LEFT JOIN dws_customer_360" in count_sql
    assert "c.customer_name = ka.`重客名称`" in count_sql
    assert "c.campaign_tag = :key_account_source_project" in count_sql
    assert "MAX(`time`)" in count_sql
    assert "ORDER BY (c.id IS NULL) ASC, c.intent_score DESC" in data_sql


def test_key_account_filter_supports_keyword_and_pagination(mock_db):
    _call(
        mock_db,
        special_project=["重客"],
        keyword=["中煤"],
        page=2,
        size=20,
    )

    count_sql, count_params = mock_db.calls[0]
    _, data_params = mock_db.calls[1]
    assert "ka.`重客名称` IN (:key_account_keyword_0)" in count_sql
    assert count_params == {
        "key_account_source_project": "企业彩光ICT",
        "key_account_keyword_0": "中煤",
    }
    assert data_params["key_account_keyword_0"] == "中煤"
    assert data_params["key_account_source_project"] == "企业彩光ICT"
    assert data_params["limit"] == 20
    assert data_params["offset"] == 20


def test_key_account_filter_applies_enriched_customer_filters(mock_db):
    result = _call(
        mock_db,
        special_project=["重客"],
        industry=["软件"],
        region=["广东"],
        owner=["张三"],
        interaction_min=3,
        attribute="heavy",
        channel=["email"],
    )

    count_sql, count_params = mock_db.calls[0]
    _, data_params = mock_db.calls[1]
    assert "LEFT JOIN dws_customer_360" in count_sql
    assert "c.industry IN (:key_account_industry_0)" in count_sql
    assert "c.region IN (:key_account_region_exact_0, :key_account_region_area_0)" in count_sql
    assert "c.owner_name IN (:key_account_owner_0)" in count_sql
    assert "dws_interaction_detail" in count_sql
    assert "EXISTS (SELECT 1 FROM dws_interaction_detail ic" in count_sql
    assert "ic.customer_name = ka.`重客名称`" in count_sql
    assert "ic.channel IN" in count_sql
    assert count_params["key_account_industry_0"] == "软件"
    assert count_params["key_account_region_exact_0"] == "广东"
    assert count_params["key_account_region_area_0"] == "广东区域"
    assert count_params["key_account_owner_0"] == "张三"
    assert count_params["interaction_min"] == 3
    assert {count_params["key_account_channel_0_0"], count_params["key_account_channel_0_1"]} == {"email", "邮件"}
    assert data_params["limit"] == 20
    assert data_params["offset"] == 0
    assert result["filters_applied"]["industry"] == ["软件"]
    assert result["filters_applied"]["attribute"] == "heavy"


def test_key_account_filter_options_are_scoped_and_regions_are_normalized(mock_db):
    mock_db.add_result(
        "SELECT c.industry, c.region, c.owner_name",
        rows=[
            {
                "industry": "制造业",
                "region": "山东区域",
                "owner_name": "重客负责人甲",
                "purchase_stage": "阶段2",
                "intent_level": "高",
                "last_interaction_channel": "web",
            },
            {
                "industry": "教育",
                "region": "企业系统部大客户一部",
                "owner_name": "重客负责人乙",
                "purchase_stage": "阶段1",
                "intent_level": "中",
                "last_interaction_channel": "邮件",
            },
        ],
    )
    mock_db.add_result(
        "SELECT DISTINCT interaction.channel",
        rows=[
            {"channel": "email"},
            {"channel": "web"},
            {"channel": "event"},
            {"channel": "4. 客户端拜访获取"},
        ],
    )

    result = get_filter_options(db=mock_db, special_project=["重客"])

    sql, params = mock_db.calls[0]
    assert "ods_crm_key_account_output_list_day" in sql
    assert "MAX(`time`)" in sql
    assert "c.customer_name = ka.`重客名称`" in sql
    assert params["filter_source_project"] == "企业彩光ICT"
    assert result["owners"] == ["重客负责人乙", "重客负责人甲"]
    assert result["regions"] == ["山东", "其他"]
    assert result["channels"] == ["email", "web", "event", "other"]


def test_key_account_keyword_and_channel_stay_within_latest_snapshot(mock_db):
    _call(
        mock_db,
        special_project=["重客"],
        keyword=["山东魏桥"],
        channel=["web"],
    )

    count_sql, params = mock_db.calls[0]
    assert "ka.`time` = (SELECT MAX(`time`)" in count_sql
    assert "ka.`重客名称` IN (:key_account_keyword_0)" in count_sql
    assert "ic.customer_name = ka.`重客名称`" in count_sql
    assert params["key_account_keyword_0"] == "山东魏桥"
    assert {params["key_account_channel_0_0"], params["key_account_channel_0_1"]} == {"web", "官网"}


def test_standard_project_filter_options_are_scoped(mock_db):
    get_filter_options(db=mock_db, special_project=["企业彩光ICT"])

    sql, params = mock_db.calls[0]
    assert "c.campaign_tag IN" in sql
    assert params["filter_other_projects"] == ("企业彩光ICT",)


def test_key_account_filter_preserves_unmatched_snapshot_row(mock_db):
    mock_db.add_result("SELECT COUNT(*)", scalar=1)
    mock_db.add_result(
        "`重客编码` AS key_account_code",
        rows=[{
            "id": None,
            "customer_name": None,
            "campaign_tag": None,
            "industry": None,
            "key_account_code": "KH-404",
            "key_account_name": "尚未进入彩光的重客",
        }],
    )

    result = _call(mock_db, special_project=["重客"])

    assert result["total"] == 1
    assert result["items"] == [{
        "id": None,
        "customer_name": "尚未进入彩光的重客",
        "campaign_tag": "重客",
        "industry": None,
        "key_account_code": "KH-404",
    }]


def test_key_account_export_uses_enriched_query_and_filters(client, mock_db):
    mock_db.add_result(
        "`重客编码` AS key_account_code",
        rows=[{
            "id": 42,
            "customer_name": "彩光侧名称",
            "campaign_tag": "企业彩光ICT",
            "industry": "制造业",
            "region": "山东",
            "owner_name": "张三",
            "purchase_stage": "需求构建",
            "intent_level": "高",
            "intent_score": 88,
            "key_account_code": "KH-001",
            "key_account_name": "测试重客集团",
        }],
    )

    response = client.get(
        "/api/customers/export",
        params={
            "special_project": "重客",
            "industry": "制造业",
            "sort": "customer_name asc",
        },
    )

    assert response.status_code == 200
    sql, params = mock_db.calls[0]
    assert "LEFT JOIN dws_customer_360" in sql
    assert "c.industry IN (:key_account_industry_0)" in sql
    assert "ka.`重客名称` ASC" in sql
    assert params["key_account_industry_0"] == "制造业"
    workbook = openpyxl.load_workbook(BytesIO(response.content))
    sheet = workbook.active
    assert sheet.cell(row=2, column=1).value == "测试重客集团"
    assert sheet.cell(row=2, column=2).value == "制造业"
    assert sheet.cell(row=2, column=5).value == "重客"
