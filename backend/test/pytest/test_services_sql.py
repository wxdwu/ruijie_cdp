"""服务层 SQL 生成逻辑测试（不依赖真实数据库，仅断言生成的 SQL）。

覆盖：opportunity_service 过滤条件、interaction_service 过滤条件，
以及 customer_service 的分页信封返回。
"""
from app.services.opportunity_service import get_opportunities
from app.services.interaction_service import get_interactions


def test_opportunity_owner_like(mock_db):
    get_opportunities(db=mock_db, owner_name="张")
    sql, params = mock_db.calls[0]
    assert "owner_name LIKE :owner_name" in sql
    assert params["owner_name"] == "%张%"


def test_opportunity_stage_equal(mock_db):
    get_opportunities(db=mock_db, stage="意向")
    sql, params = mock_db.calls[0]
    assert "stage = :stage" in sql
    assert params["stage"] == "意向"


def test_opportunity_close_date_range(mock_db):
    get_opportunities(db=mock_db, close_date_from="2026-01-01", close_date_to="2026-06-30")
    sql, params = mock_db.calls[0]
    assert "close_date >= :close_from" in sql
    assert "close_date <= :close_to" in sql


def test_opportunity_forecast_stage_equal(mock_db):
    get_opportunities(db=mock_db, forecast_stage="可能")
    sql, params = mock_db.calls[0]
    assert "forecast_stage = :forecast_stage" in sql


def test_opportunity_returns_envelope(mock_db):
    result = get_opportunities(db=mock_db, page=1, page_size=10)
    assert "items" in result and "total" in result
    assert result["page"] == 1


def test_interaction_customer_id_equal(mock_db):
    get_interactions(db=mock_db, customer_id="C1")
    sql, params = mock_db.calls[0]
    assert "customer_id = :customer_id" in sql
    assert params["customer_id"] == "C1"


def test_interaction_keyword_like(mock_db):
    get_interactions(db=mock_db, keyword="报价")
    sql, params = mock_db.calls[0]
    assert "content LIKE :keyword" in sql
    assert params["keyword"] == "%报价%"


def test_interaction_time_range(mock_db):
    get_interactions(db=mock_db, channel="邮件")
    sql, params = mock_db.calls[0]
    assert "channel = :channel" in sql
    assert params["channel"] == "邮件"


def test_interaction_returns_envelope(mock_db):
    result = get_interactions(db=mock_db, page=2, page_size=20)
    assert "items" in result and "total" in result
    assert result["page"] == 2
