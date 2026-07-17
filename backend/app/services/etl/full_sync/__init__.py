"""ETL 全量同步子包（full_sync）。

包含：锚点表构建（anchor_tables）、4 张 DWS 目标表的构建器（build_dws_*），
以及全量编排入口（pipeline.run_full_sync）。
"""
from app.services.etl.full_sync.anchor_tables import (
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
from app.services.etl.full_sync.build_dws_contact_mapping import _load_contact_mapping
from app.services.etl.full_sync.build_dws_interaction_detail import (
    _build_zhique_channel_case,
    _load_interactions_zhique,
    _load_interactions_tianrun,
    _load_interactions_linkflow,
    _load_interactions_crm_lead,
    _load_interactions_crm_opportunity,
    _load_interaction_detail,
)
from app.services.etl.full_sync.build_dws_customer_360 import _build_customer_360
from app.services.etl.full_sync.build_dws_contact_360 import _build_contact_360
from app.services.etl.full_sync.pipeline import run_full_sync

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
    "_load_contact_mapping",
    "_build_zhique_channel_case",
    "_load_interactions_zhique",
    "_load_interactions_tianrun",
    "_load_interactions_linkflow",
    "_load_interactions_crm_lead",
    "_load_interactions_crm_opportunity",
    "_load_interaction_detail",
    "_build_customer_360",
    "_build_contact_360",
    "run_full_sync",
]
