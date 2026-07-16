"""公司去重证据评分回归测试。

守护此前修复的 bug：batch_calculate_evidence_scores 曾对每个公司名生成一条
`related_company LIKE :name_N` 条件并用 OR 串联（公司数上千时产生巨型 SQL），
现已改为精确 `IN (...)` 匹配。
"""
from conftest import MockDBSession

from app.services.company_dedup.company_dedup import batch_calculate_evidence_scores


PAIRS = [
    ("华为技术有限公司", "华为投资控股有限公司"),
    ("腾讯科技（深圳）有限公司", "腾讯云计算（北京）有限责任公司"),
]


def test_evidence_scores_uses_in_not_like():
    db = MockDBSession()
    batch_calculate_evidence_scores(PAIRS, db)

    ods_sqls = [
        s
        for s, _ in db.calls
        if ("FROM ods_zhique_contact_day" in s
            or "FROM ods_crm_contact_day" in s
            or "FROM ods_marketing_lead_day" in s)
    ]
    assert ods_sqls, "应当生成针对 ODS 表的查询"
    for sql in ods_sqls:
        assert "IN (" in sql, f"期望 IN 匹配，实际: {sql}"
        assert "LIKE" not in sql, f"不应出现 LIKE 链式条件，实际: {sql}"


def test_evidence_scores_returns_dict_on_empty(mock_db):
    # 默认 mock 不返回任何行 -> 无共享联系人 -> 每个 pair 的证据分为 0
    result = batch_calculate_evidence_scores(PAIRS, mock_db)
    assert isinstance(result, dict)
    for pair in PAIRS:
        assert pair in result
        score, shared_count, evidences = result[pair]
        assert score == 0.0
        assert shared_count == 0
        assert evidences == []
