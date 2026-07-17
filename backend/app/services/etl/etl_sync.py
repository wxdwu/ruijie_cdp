"""
ETL 同步兼容门面（facade）。

原 etl_sync.py 已将代码按职责拆分为：
  - app.services.etl.common.*            ：共享底层（DB 引擎、锚点/临时表、水位、sync_meta）
  - app.services.etl.full_sync.*         ：全量同步（锚点表 + 4 个 DWS 构建 + pipeline）
  - app.services.etl.incremental_sync.*  ：增量同步（同上结构）

为保持对外接口（main / routers / es_sync / scheduler / 单测）零改动，
本模块仅做再导出（re-export）。
"""
from app.services.etl.common.db import get_etl_engine
from app.services.etl.common.anchor import (
    _build_tmp_icp_filters,
    _create_etl_temp_tables,
    _ETL_TEMP_TABLES,
)
from app.services.etl.common.watermark import ensure_schema_for_incremental
from app.services.etl.full_sync.build_dws_contact_mapping import _load_contact_mapping
from app.services.etl.full_sync.pipeline import run_full_sync
from app.services.etl.incremental_sync.pipeline import run_incremental_sync

__all__ = [
    "get_etl_engine",
    "_build_tmp_icp_filters",
    "_create_etl_temp_tables",
    "_ETL_TEMP_TABLES",
    "ensure_schema_for_incremental",
    "_load_contact_mapping",
    "run_full_sync",
    "run_incremental_sync",
]
