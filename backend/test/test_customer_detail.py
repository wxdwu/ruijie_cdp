"""Customer detail API tests."""
from __future__ import annotations

import unittest

from app.routers.customer_detail import get_customer_detail


class _MappingResult:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def fetchone(self):
        return self.row


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class _RecordingDb:
    def __init__(self):
        self.calls = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, dict(params or {})))
        if "FROM dws_customer_360" in sql:
            return _MappingResult({
                "id": 916,
                "customer_name": "贵州茅台酒股份有限公司",
                "interaction_count_30d": 116,
            })
        if "FROM dws_interaction_detail" in sql:
            return _ScalarResult(0)
        if "FROM ods_crm_contact_day" in sql:
            return _MappingResult(None)
        raise AssertionError(f"Unexpected SQL: {sql}")


class TestCustomerDetail(unittest.TestCase):
    def test_detail_overrides_aggregate_30d_count_with_today_based_count(self):
        db = _RecordingDb()

        result = get_customer_detail("916", db=db)

        self.assertEqual(result["interaction_count_30d"], 0)
        interaction_sql, interaction_params = db.calls[1]
        self.assertIn("dws_interaction_detail", interaction_sql)
        self.assertIn("DATE_SUB(NOW(), INTERVAL 30 DAY)", interaction_sql)
        self.assertEqual(interaction_params["cname"], "贵州茅台酒股份有限公司")


if __name__ == "__main__":
    unittest.main()
