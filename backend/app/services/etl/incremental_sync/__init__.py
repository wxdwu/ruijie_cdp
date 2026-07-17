"""ETL 增量同步子包（incremental_sync）。

包含：锚点表构建（anchor_tables）、4 张 DWS 目标表的增量构建器（build_dws_*），
以及增量编排入口（pipeline.run_incremental_sync）。
"""
from app.services.etl.incremental_sync.anchor_tables import (
    _build_icp_customers_table,
    _drop_etl_temp_tables,
    _create_etl_temp_tables,
    _build_tmp_icp_filters,
    _build_tmp_crm_mobiles,
    _build_tmp_valid_linkflow_contacts,
    _build_tmp_crm_aggregates,
    _phase_start,
    _phase_end,
)
from app.services.etl.incremental_sync.build_dws_contact_mapping import (
    _incremental_update_icp_customers,
    _incremental_upsert_contact_mapping,
)
from app.services.etl.incremental_sync.build_dws_interaction_detail import (
    _incremental_upsert_interaction_detail,
    _incremental_load_tianrun,
    _incremental_load_linkflow,
    _incremental_load_crm_lead,
    _incremental_load_crm_opportunity,
)
from app.services.etl.incremental_sync.build_dws_customer_360 import (
    _get_affected_customers,
    _incremental_build_customer_360,
    _incremental_rebuild_aggregates,
)
from app.services.etl.incremental_sync.build_dws_contact_360 import (
    _build_contact_360,
    _incremental_build_contact_360,
)
from app.services.etl.incremental_sync.pipeline import run_incremental_sync

__all__ = [
    "_build_icp_customers_table",
    "_drop_etl_temp_tables",
    "_create_etl_temp_tables",
    "_build_tmp_icp_filters",
    "_build_tmp_crm_mobiles",
    "_build_tmp_valid_linkflow_contacts",
    "_build_tmp_crm_aggregates",
    "_phase_start",
    "_phase_end",
    "_incremental_update_icp_customers",
    "_incremental_upsert_contact_mapping",
    "_incremental_upsert_interaction_detail",
    "_incremental_load_tianrun",
    "_incremental_load_linkflow",
    "_incremental_load_crm_lead",
    "_incremental_load_crm_opportunity",
    "_get_affected_customers",
    "_incremental_build_customer_360",
    "_incremental_rebuild_aggregates",
    "_build_contact_360",
    "_incremental_build_contact_360",
    "run_incremental_sync",
]
