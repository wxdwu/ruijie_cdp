"""ETL 逻辑回归测试。

守护此前修复的 bug：
- dws_contact_mapping 载入查询必须引用持久锚点表 tmp_icp_customers，
  而非已被废弃/未创建的 tmp_icp_companies（见前次修复）。
- 临时表列表中不应再包含 tmp_icp_companies。
"""
import inspect

from app.services.etl import etl_sync
from app.services.etl.common.anchor import _build_icp_customers_table
from app.services.etl.incremental_sync.build_dws_contact_mapping import (
    _incremental_upsert_contact_mapping,
)


def test_contact_mapping_uses_tmp_icp_customers():
    src = inspect.getsource(etl_sync._load_contact_mapping)
    assert "tmp_icp_customers" in src
    assert "tmp_icp_companies" not in src


def test_build_tmp_icp_filters_uses_customers():
    src = inspect.getsource(etl_sync._build_tmp_icp_filters)
    # 必须向 tmp_icp_customers 写入，且不得再创建 tmp_icp_companies 表
    assert "INSERT IGNORE INTO tmp_icp_customers" in src
    assert "CREATE TABLE tmp_icp_companies" not in src


def test_create_etl_temp_tables_no_companies():
    src = inspect.getsource(etl_sync._create_etl_temp_tables)
    assert "CREATE TABLE tmp_icp_companies" not in src


def test_etl_temp_tables_excludes_companies():
    assert "tmp_icp_companies" not in etl_sync._ETL_TEMP_TABLES


def test_detail_table_registered_for_sync():
    """ods_zhique_contact_detail_day 必须登记进 ODS 表清单与增量水位配置。"""
    from app.services.etl.common.constants import _ODS_TABLES
    from app.services.etl.common.watermark import ODS_INCREMENTAL_CONFIG

    assert "ods_zhique_contact_detail_day" in _ODS_TABLES
    assert ODS_INCREMENTAL_CONFIG.get("ods_zhique_contact_detail_day", {}).get("field") == "time"


def test_full_contact_mapping_includes_detail():
    """全量 _load_contact_mapping 须将 detail 表按 zhique_detail 源追加进 contact_mapping。"""
    src = inspect.getsource(etl_sync._load_contact_mapping)
    assert "ods_zhique_contact_detail_day" in src
    assert "'zhique_detail'" in src


def test_incremental_contact_mapping_includes_detail():
    """增量 _incremental_upsert_contact_mapping 须追加 detail 表并回写 time 水位。"""
    src = inspect.getsource(_incremental_upsert_contact_mapping)
    assert "ods_zhique_contact_detail_day" in src
    assert "'zhique_detail'" in src
    assert "_set_watermark_after_load(\"ods_zhique_contact_detail_day\")" in src


def test_icp_anchor_includes_detail():
    """ICP 锚点（全量 _build_icp_customers_table 与 _build_tmp_icp_filters）须纳入 detail 表。"""
    src_full = inspect.getsource(_build_icp_customers_table)
    src_filters = inspect.getsource(etl_sync._build_tmp_icp_filters)
    assert "ods_zhique_contact_detail_day" in src_full
    assert "ods_zhique_contact_detail_day" in src_filters

