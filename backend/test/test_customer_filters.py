"""Customer list filter SQL tests."""
from __future__ import annotations

import unittest

from app.routers.customer_list import list_customers
from app.services.customer_service import get_customer_list
from app.services.export_service import export_customers_excel


class _EmptyResult:
    def scalar(self):
        return 0

    def mappings(self):
        return self

    def all(self):
        return []


class _RecordingDb:
    def __init__(self):
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), dict(params or {})))
        return _EmptyResult()


def _run_router_query(db, **filters):
    list_customers(
        db=db,
        keyword=None,
        industry=None,
        region=filters.get("region"),
        region_keyword=filters.get("region_keyword"),
        owner=None,
        owner_keyword=None,
        stage=None,
        intent_level=None,
        interaction_min=None,
        interaction_period=30,
        attribute=filters.get("attribute"),
        channel=None,
        sort=None,
        page=1,
        size=20,
    )


def _run_service_query(db, **filters):
    get_customer_list(db=db, **filters)


def _run_export_query(db, **filters):
    export_customers_excel(db=db, **filters)


class TestCustomerFilters(unittest.TestCase):
    runners = [_run_router_query, _run_service_query, _run_export_query]

    def test_region_filter_uses_equal_condition_for_standard_region(self):
        for runner in self.runners:
            with self.subTest(runner=runner.__name__):
                db = _RecordingDb()

                runner(db, region="广东")

                sql, params = db.calls[0]
                self.assertIn("region = :region", sql)
                self.assertEqual(params["region"], "广东")

    def test_region_filter_groups_other_values(self):
        for runner in self.runners:
            with self.subTest(runner=runner.__name__):
                db = _RecordingDb()

                runner(db, region="其他")

                sql, params = db.calls[0]
                self.assertIn("region IS NULL", sql)
                self.assertIn("region = ''", sql)
                self.assertIn("region NOT IN", sql)
                self.assertEqual(params["standard_region_0"], "广东")
                self.assertNotIn("region", params)

    def test_region_keyword_other_uses_other_region_condition(self):
        for runner in self.runners:
            with self.subTest(runner=runner.__name__):
                db = _RecordingDb()

                runner(db, region_keyword="其他")

                sql, params = db.calls[0]
                self.assertIn("region NOT IN", sql)
                self.assertEqual(params["standard_region_0"], "广东")
                self.assertNotIn("region_keyword", params)

    def test_region_keyword_uses_like_condition(self):
        for runner in self.runners:
            with self.subTest(runner=runner.__name__):
                db = _RecordingDb()

                runner(db, region_keyword="广")

                sql, params = db.calls[0]
                self.assertIn("region LIKE :region_keyword", sql)
                self.assertEqual(params["region_keyword"], "%广%")

    def test_heavy_attribute_filter_uses_h_rating(self):
        for runner in self.runners:
            with self.subTest(runner=runner.__name__):
                db = _RecordingDb()

                runner(db, attribute="heavy")

                sql, params = db.calls[0]
                self.assertIn("attribute = :heavy_attribute", sql)
                self.assertEqual(params["heavy_attribute"], "H")

    def test_non_heavy_attribute_filter_includes_null_and_non_h(self):
        for runner in self.runners:
            with self.subTest(runner=runner.__name__):
                db = _RecordingDb()

                runner(db, attribute="non_heavy")

                sql, params = db.calls[0]
                self.assertIn("(attribute IS NULL OR attribute != :heavy_attribute)", sql)
                self.assertEqual(params["heavy_attribute"], "H")


if __name__ == "__main__":
    unittest.main()
