"""ETL 共享底层模块（common/constants.py）。

本文件从原 etl_sync.py 抽取，SQL 与调用语义保持不变，仅供 full_sync / incremental_sync 通过 `from app.services.etl.common import *` 复用。"""

from __future__ import annotations

import logging


logger = logging.getLogger(__name__)



# 以下函数/常量由原 etl_sync.py 抽取，SQL 与调用语义保持不变
BATCH_SIZE = 10_000


ROLE_MAP: Dict[str, str] = {
    "拍板者": "决策者",
    "决策者": "决策者",
    "评估者": "技术评估者",
    "使用者": "使用者",
    "其他":   "其他",
    "未知":   "未知",
}


ZHIQUE_CHANNEL_MAP: Dict[str, str] = {
    "打开邮件":       "email",
    "点击邮件链接":   "email",
    "报名会议":       "event",
    "参会":           "event",
    "观看直播":       "event",
    "下载资料":       "web",
    "单页面表单提交": "web",
    "访问落地页":     "web",
}


LINKFLOW_DEFAULT_CHANNEL = "web"


def _build_zhique_channel_case() -> str:
    """Build SQL CASE expression for Zhique behavior_type → channel.

    全量/增量同步共用的共享原语，下沉到 common 以避免子包间相互依赖。
    """
    parts = " ".join(
        f"WHEN b.behavior_type = '{k}' THEN '{v}'"
        for k, v in ZHIQUE_CHANNEL_MAP.items()
    )
    return f"CASE {parts} ELSE 'other' END"


_ODS_TABLES = [
    "ods_crm_contact_day",
    "ods_crm_opportunity_day",
    "ods_zhique_contact_day",
    "ods_marketing_lead_day",
    "ods_zhique_behavior_list_day",
    "ods_tianrun_session_day",
    "ods_linkflow_contacts_day",
    "ods_linkflow_events_day",
    "ods_ruijie_website_user_day",
    "ods_tianrun_customer_profile_day",
]
