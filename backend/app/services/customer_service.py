"""
客户 360 查询服务。

集中维护 dws_customer_360 的列表查询与筛选条件构建，供
customer_list 路由、export_service 导出等复用，避免过滤逻辑散落多份、重复实现。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.channel_classification import add_customer_interaction_channel_filter
from app.services.region_filter import add_region_filter

logger = logging.getLogger(__name__)

# 允许排序的字段（白名单，防止 SQL 注入）
ALLOWED_SORT = {
    "customer_name", "industry", "intent_score", "interaction_count_30d",
    "interaction_count_total", "last_interaction_time", "active_opp_amount",
    "won_amount", "updated_at",
}


def get_customer_list(
    db: Session,
    *,
    keyword: Optional[str] = None,
    special_project: Optional[str] = None,
    industry: Optional[str] = None,
    region: Optional[str] = None,
    region_keyword: Optional[str] = None,
    owner: Optional[str] = None,
    owner_keyword: Optional[str] = None,
    stage: Optional[str] = None,
    intent_level: Optional[str] = None,
    interaction_min: Optional[int] = None,
    interaction_period: int = 30,
    attribute: Optional[str] = None,
    channel: Optional[str] = None,
    sort: str = "intent_score DESC",
    page: int = 1,
    page_size: int = 50,
) -> Dict[str, Any]:
    """查询 dws_customer_360，支持多维度筛选、排序与分页。

    作为客户列表 / 导出等场景的唯一查询来源，统一过滤逻辑。
    返回 {items, total, page, page_size, filters_applied}。
    """
    where_parts: List[str] = ["1=1"]
    params: Dict[str, Any] = {}

    if keyword:
        where_parts.append("customer_name LIKE :keyword")
        params["keyword"] = f"%{keyword}%"
    if special_project:
        where_parts.append("campaign_tag = :special_project")
        params["special_project"] = special_project
    if industry:
        where_parts.append("industry = :industry")
        params["industry"] = industry
    # 区域筛选（兼容「广东」与「广东区域」两种写法）
    add_region_filter(
        where_parts, params,
        column="region", region=region, region_keyword=region_keyword,
    )
    if owner:
        where_parts.append("owner_name = :owner")
        params["owner"] = owner
    elif owner_keyword:
        where_parts.append("owner_name LIKE :owner_keyword")
        params["owner_keyword"] = f"%{owner_keyword}%"
    if stage:
        where_parts.append("purchase_stage = :stage")
        params["stage"] = stage
    if intent_level:
        where_parts.append("intent_level = :intent_level")
        params["intent_level"] = intent_level
    if interaction_min is not None and interaction_min > 0:
        # 指定时间窗口内的互动次数需达到阈值
        where_parts.append("""
            customer_name IN (
                SELECT customer_name
                FROM dws_interaction_detail
                WHERE event_time >= DATE_SUB(NOW(), INTERVAL :period DAY)
                GROUP BY customer_name
                HAVING COUNT(*) >= :interaction_min
            )
        """)
        params["interaction_min"] = interaction_min
        params["period"] = interaction_period
    if attribute == "heavy":
        where_parts.append("attribute = :heavy_attribute")
        params["heavy_attribute"] = "H"
    elif attribute == "non_heavy":
        where_parts.append("(attribute IS NULL OR attribute != :heavy_attribute)")
        params["heavy_attribute"] = "H"
    # 渠道筛选（基于互动明细 EXISTS 子查询）
    add_customer_interaction_channel_filter(
        where_parts, params,
        customer_name_column="dws_customer_360.customer_name",
        channel=channel,
    )

    where_sql = " AND ".join(where_parts)

    total = db.execute(
        text(f"SELECT COUNT(*) FROM dws_customer_360 WHERE {where_sql}"),
        params,
    ).scalar() or 0

    # 排序解析（"字段 [ASC|DESC]"）；非法字段回退到 intent_score
    sort_by = "intent_score"
    sort_order = "DESC"
    if sort:
        parts = sort.strip().split()
        if parts[0] in ALLOWED_SORT:
            sort_by = parts[0]
        if len(parts) > 1 and parts[1].upper() == "ASC":
            sort_order = "ASC"

    offset = (max(1, page) - 1) * page_size
    rows = db.execute(
        text(
            f"SELECT * FROM dws_customer_360 "
            f"WHERE {where_sql} "
            f"ORDER BY {sort_by} {sort_order} "
            f"LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": page_size, "offset": offset},
    ).mappings().all()
    items = [dict(r) for r in rows]

    filters_applied = {
        "keyword": keyword,
        "special_project": special_project,
        "industry": industry,
        "region": region,
        "region_keyword": region_keyword,
        "owner": owner,
        "owner_keyword": owner_keyword,
        "stage": stage,
        "intent_level": intent_level,
        "interaction_min": interaction_min,
        "interaction_period": interaction_period,
        "attribute": attribute,
        "channel": channel,
        "sort": sort,
    }

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "filters_applied": filters_applied,
    }
