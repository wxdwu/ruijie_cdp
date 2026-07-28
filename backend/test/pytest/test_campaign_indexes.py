"""营销查询索引的幂等创建与 ETL 轮换覆盖测试。"""

from app.services.etl.common import db as db_module


def test_online_index_creation_is_idempotent(monkeypatch):
    statements = []
    monkeypatch.setattr(db_module, "_exec_query", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        db_module,
        "_exec",
        lambda sql, _params=None: statements.append(sql) or 0,
    )

    created = db_module._ensure_index(
        "dws_customer_360",
        "idx_campaign_default_sort",
        "campaign_tag, intent_score DESC",
        online=True,
    )

    assert created is True
    assert statements == [
        "ALTER TABLE dws_customer_360 "
        "ADD INDEX idx_campaign_default_sort (campaign_tag, intent_score DESC), "
        "ALGORITHM=INPLACE, LOCK=NONE"
    ]

    statements.clear()
    monkeypatch.setattr(db_module, "_exec_query", lambda *_args, **_kwargs: [(1,)])
    assert db_module._ensure_index(
        "dws_customer_360",
        "idx_campaign_default_sort",
        "campaign_tag, intent_score DESC",
        online=True,
    ) is False
    assert statements == []


def test_campaign_indexes_cover_main_backup_and_rotation_temp(monkeypatch):
    ensured = []
    executed = []

    def fake_ensure(table, index_name, columns, *, online=False):
        ensured.append((table, index_name, columns, online))
        return table.startswith(("dws_customer_360", "dws_interaction_detail"))

    monkeypatch.setattr(db_module, "_ensure_index", fake_ensure)
    monkeypatch.setattr(db_module, "_table_exists", lambda _table: True)
    monkeypatch.setattr(
        db_module,
        "_exec",
        lambda sql, _params=None: executed.append(sql) or 0,
    )

    db_module._create_indexes()

    campaign_calls = [call for call in ensured if call[0].startswith("dws_")]
    for base_table in ("dws_customer_360", "dws_interaction_detail"):
        for suffix in ("", "_backup", "_temp"):
            assert any(
                table == f"{base_table}{suffix}" and online
                for table, _name, _columns, online in campaign_calls
            )
            assert f"ANALYZE TABLE {base_table}{suffix}" in executed
