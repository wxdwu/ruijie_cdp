"""ETL 逻辑回归测试。

守护此前修复的 bug：
- dws_contact_mapping 载入查询必须引用持久锚点表 tmp_icp_customers，
  而非已被废弃/未创建的 tmp_icp_companies（见前次修复）。
- 临时表列表中不应再包含 tmp_icp_companies。
"""
import inspect

from app.services import etl_sync


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
