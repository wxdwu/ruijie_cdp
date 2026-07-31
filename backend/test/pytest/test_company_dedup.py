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

    # 当前证据来源为 DWS 聚合表（EVIDENCE_TABLES），须用 IN (...) 精确匹配公司名
    dws_sqls = [
        s
        for s, _ in db.calls
        if ("FROM dws_contact_mapping" in s
            or "FROM dws_interaction_detail" in s)
    ]
    assert dws_sqls, "应当生成针对 DWS 证据表的查询"
    for sql in dws_sqls:
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


def test_shared_contact_requires_name_and_phone():
    """回归：共享联系人必须「姓名 + 电话」都相同。

    仅电话相同而姓名不同（如 A 的「张三」与 B 的「李四」共用一个号码）不算共享；
    只有姓名与电话都相同的「王五」才算 1 个共享联系人。
    """
    db = MockDBSession()
    phone_rows = [
        {"customer_name": "公司A", "mobile": "13800000000", "contact_name": "张三"},
        {"customer_name": "公司B", "mobile": "13800000000", "contact_name": "李四"},  # 同号不同名 → 不计
        {"customer_name": "公司A", "mobile": "13900000000", "contact_name": "王五"},
        {"customer_name": "公司B", "mobile": "13900000000", "contact_name": "王五"},  # 同名同号 → 计 1
    ]
    db.add_result("mobile", rows=phone_rows)
    db.add_result("email", rows=[])

    result = batch_calculate_evidence_scores([("公司A", "公司B")], db)
    score, shared_count, details = result[("公司A", "公司B")]
    assert shared_count == 1, f"仅电话相同不应计为共享联系人，期望 1，实际 {shared_count}"
    assert len(details) == 1
    assert details[0]["name"] == "王五"
    assert details[0]["type"] == "phone"


def test_shared_contact_phone_format_normalized():
    """回归：号码格式不一致（+86 / 空格）但归一化后相同且姓名一致，应识别为共享。"""
    db = MockDBSession()
    phone_rows = [
        {"customer_name": "公司A", "mobile": "+86 138 0000 1111", "contact_name": "赵六"},
        {"customer_name": "公司B", "mobile": "8613800001111", "contact_name": "赵六"},
    ]
    db.add_result("mobile", rows=phone_rows)
    db.add_result("email", rows=[])

    result = batch_calculate_evidence_scores([("公司A", "公司B")], db)
    score, shared_count, details = result[("公司A", "公司B")]
    assert shared_count == 1, f"号码格式不同但归一化相同应算共享，期望 1，实际 {shared_count}"
    assert details[0]["name"] == "赵六"
