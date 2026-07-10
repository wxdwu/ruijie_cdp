"""ETL 增量同步水位逻辑测试（service 层，mock DB 辅助函数）。

覆盖：
  - ODS_INCREMENTAL_CONFIG 配置完整性（10 张表、模式/字段/类型正确）
  - _watermark_filter 按配置生成过滤片段（全量 / 时间 / unix 时间 / ID / 无水位）
  - _set_watermark_after_load 写回水位 SQL（时间→last_sync_time，ID→last_watermark_value，unix→FROM_UNIXTIME）
"""
from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import patch

from app.services import etl_sync


class TestIncrementalConfig(unittest.TestCase):
    def test_config_contains_all_10_tables(self):
        cfg = etl_sync.ODS_INCREMENTAL_CONFIG
        self.assertEqual(len(cfg), 10)
        expected = {
            "ods_zhique_behavior_list_day":       ("incremental", "behavior_time",   "time"),
            "ods_linkflow_contacts_day":          ("incremental", "contact_id",      "id"),
            "ods_linkflow_events_day":            ("incremental", "extra_id",        "id"),
            "ods_tianrun_session_day":            ("incremental", "start_time_sec",  "unix_time"),
            "ods_tianrun_customer_profile_day":   ("full", None, None),
            "ods_crm_opportunity_data_day":        ("full", None, None),
            "ods_crm_lead_data_day":               ("full", None, None),
            "ods_crm_key_account_output_list_day": ("full", None, None),
            "ods_tianrun_session_detail_day":      ("incremental", "start_time_sec",  "unix_time"),
            "ods_ruijie_website_user_day":         ("incremental", "register_time",   "time"),
        }
        for name, (mode, field, ftype) in expected.items():
            self.assertIn(name, cfg, f"缺少配置: {name}")
            self.assertEqual(cfg[name]["mode"], mode, name)
            self.assertEqual(cfg[name].get("field"), field, name)
            self.assertEqual(cfg[name].get("field_type"), ftype, name)


class TestWatermarkFilter(unittest.TestCase):
    @patch("app.services.etl_sync._get_last_sync_time")
    @patch("app.services.etl_sync._get_last_watermark_id")
    def test_full_table_returns_no_filter(self, mock_id, mock_time):
        clause, wm = etl_sync._watermark_filter("ods_tianrun_customer_profile_day", "t")
        self.assertEqual(clause, "")
        self.assertIsNone(wm)

    @patch("app.services.etl_sync._get_last_sync_time", return_value=datetime(2026, 7, 1, 0, 0, 0))
    @patch("app.services.etl_sync._get_last_watermark_id")
    def test_time_field_uses_behavior_time(self, mock_id, mock_time):
        clause, wm = etl_sync._watermark_filter("ods_zhique_behavior_list_day", "b")
        self.assertIn("b.behavior_time > :watermark", clause)
        self.assertEqual(wm, datetime(2026, 7, 1, 0, 0, 0))

    @patch("app.services.etl_sync._get_last_sync_time")
    @patch("app.services.etl_sync._get_last_watermark_id", return_value=500)
    def test_id_field_uses_contact_id(self, mock_id, mock_time):
        clause, wm = etl_sync._watermark_filter("ods_linkflow_contacts_day", "l")
        self.assertIn("l.contact_id > :watermark", clause)
        self.assertEqual(wm, 500)

    @patch("app.services.etl_sync._get_last_sync_time", return_value=datetime(2026, 7, 1))
    @patch("app.services.etl_sync._get_last_watermark_id")
    def test_unix_time_field_wraps_from_unixtime(self, mock_id, mock_time):
        clause, wm = etl_sync._watermark_filter("ods_tianrun_session_day", "s")
        self.assertIn("FROM_UNIXTIME(s.start_time_sec) > :watermark", clause)

    @patch("app.services.etl_sync._get_last_sync_time", return_value=None)
    @patch("app.services.etl_sync._get_last_watermark_id")
    def test_no_watermark_returns_no_filter(self, mock_id, mock_time):
        clause, wm = etl_sync._watermark_filter("ods_zhique_behavior_list_day", "b")
        self.assertEqual(clause, "")
        self.assertIsNone(wm)


class TestSetWatermarkAfterLoad(unittest.TestCase):
    @patch("app.services.etl_sync._exec")
    def test_time_field_writes_last_sync_time(self, mock_exec):
        etl_sync._set_watermark_after_load("ods_zhique_behavior_list_day")
        sql = mock_exec.call_args[0][0]
        self.assertIn("last_sync_time", sql)
        self.assertIn("MAX(behavior_time)", sql)
        self.assertIn("ods_zhique_behavior_list_day", sql)

    @patch("app.services.etl_sync._exec")
    def test_unix_time_field_writes_from_unixtime_max(self, mock_exec):
        etl_sync._set_watermark_after_load("ods_tianrun_session_day")
        sql = mock_exec.call_args[0][0]
        self.assertIn("last_sync_time", sql)
        self.assertIn("FROM_UNIXTIME(MAX(start_time_sec))", sql)

    @patch("app.services.etl_sync._exec")
    def test_id_field_writes_last_watermark_value(self, mock_exec):
        etl_sync._set_watermark_after_load("ods_linkflow_contacts_day")
        sql = mock_exec.call_args[0][0]
        self.assertIn("last_watermark_value", sql)
        self.assertIn("MAX(contact_id)", sql)

    @patch("app.services.etl_sync._exec")
    def test_full_table_does_not_write(self, mock_exec):
        etl_sync._set_watermark_after_load("ods_tianrun_customer_profile_day")
        mock_exec.assert_not_called()


if __name__ == "__main__":
    unittest.main()
