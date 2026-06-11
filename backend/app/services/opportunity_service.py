"""
Query service for ods_crm_opportunity_day.

Provides opportunity pipeline data for the CRM / pipeline views.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Stage mappings (standalone, no external dependency)
STAGE_MAP = {
    "阶段0：未接触上客户": "未接触",
    "阶段1：接触上客户，初步交流；": "问题识别",
    "阶段2：正式交流，价值认可": "解决方案探索",
    "阶段3：测试/入围，愿意尝试": "解决方案探索",
    "阶段4：拿到门票，进入招投标": "需求构建",
    "阶段5：已中标，等待采购": "需求构建",
    "阶段6：完成采购，实现进入": "已完成",
}

FORECAST_STAGE = {
    "线索": "问题识别", "机会-": "问题识别", "机会": "问题识别",
    "机会+": "解决方案探索", "可能-": "解决方案探索",
    "可能": "需求构建", "可能+": "需求构建",
    "优势": "需求构建", "确保": "需求构建",
}


def get_opportunities(
    db: Session,
    *,
    customer_id: Optional[str] = None,
    owner_name: Optional[str] = None,
    stage: Optional[str] = None,
    forecast_stage: Optional[str] = None,
    close_date_from: Optional[date] = None,
    close_date_to: Optional[date] = None,
    min_amount: Optional[float] = None,
    sort_by: str = "close_date",
    sort_order: str = "DESC",
    page: int = 1,
    page_size: int = 50,
) -> Dict[str, Any]:
    """Query ods_crm_opportunity_day with filters and pagination.

    Returns:
        Dict with items, total, page, page_size.
    """
    where_parts: List[str] = ["1=1"]
    params: Dict[str, Any] = {}

    if customer_id:
        where_parts.append("account_id = :customer_id")
        params["customer_id"] = customer_id
    if owner_name:
        where_parts.append("owner_name LIKE :owner_name")
        params["owner_name"] = f"%{owner_name}%"
    if stage:
        where_parts.append("stage = :stage")
        params["stage"] = stage
    if forecast_stage:
        where_parts.append("forecast_stage = :forecast_stage")
        params["forecast_stage"] = forecast_stage
    if close_date_from:
        where_parts.append("close_date >= :close_from")
        params["close_from"] = close_date_from
    if close_date_to:
        where_parts.append("close_date <= :close_to")
        params["close_to"] = close_date_to
    if min_amount is not None:
        where_parts.append("amount >= :min_amount")
        params["min_amount"] = min_amount

    where_sql = " AND ".join(where_parts)

    count_sql = text(f"SELECT COUNT(*) FROM ods_crm_opportunity_day WHERE {where_sql}")
    total: int = db.execute(count_sql, params).scalar() or 0

    allowed_sort = {"close_date", "amount", "stage", "created_date", "opportunity_name"}
    if sort_by not in allowed_sort:
        sort_by = "close_date"
    order_dir = "ASC" if sort_order.upper() == "ASC" else "DESC"

    offset = (max(1, page) - 1) * page_size
    data_sql = text(
        f"SELECT * FROM ods_crm_opportunity_day "
        f"WHERE {where_sql} "
        f"ORDER BY {sort_by} {order_dir} "
        f"LIMIT :limit OFFSET :offset"
    )
    params["limit"] = page_size
    params["offset"] = offset

    rows = db.execute(data_sql, params).mappings().all()

    # Enrich with localised stage labels
    items = []
    for r in rows:
        row = dict(r)
        row["stage_label"] = STAGE_MAP.get(row.get("stage", ""), row.get("stage", ""))
        row["forecast_label"] = FORECAST_STAGE.get(
            row.get("forecast_stage", ""), row.get("forecast_stage", "")
        )
        items.append(row)

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_pipeline_summary(
    db: Session,
    *,
    owner_name: Optional[str] = None,
    close_date_from: Optional[date] = None,
    close_date_to: Optional[date] = None,
) -> Dict[str, Any]:
    """Aggregate pipeline by stage with total amounts and counts."""
    where_parts: List[str] = ["1=1"]
    params: Dict[str, Any] = {}

    if owner_name:
        where_parts.append("owner_name LIKE :owner_name")
        params["owner_name"] = f"%{owner_name}%"
    if close_date_from:
        where_parts.append("close_date >= :close_from")
        params["close_from"] = close_date_from
    if close_date_to:
        where_parts.append("close_date <= :close_to")
        params["close_to"] = close_date_to

    where_sql = " AND ".join(where_parts)

    sql = text(
        f"SELECT stage, forecast_stage, "
        f"  COUNT(*) AS opp_count, "
        f"  SUM(amount) AS total_amount, "
        f"  AVG(probability) AS avg_probability "
        f"FROM ods_crm_opportunity_day "
        f"WHERE {where_sql} "
        f"GROUP BY stage, forecast_stage "
        f"ORDER BY total_amount DESC"
    )
    rows = db.execute(sql, params).mappings().all()

    stages = []
    for r in rows:
        row = dict(r)
        row["stage_label"] = STAGE_MAP.get(row.get("stage", ""), row.get("stage", ""))
        row["forecast_label"] = FORECAST_STAGE.get(
            row.get("forecast_stage", ""), row.get("forecast_stage", "")
        )
        row["total_amount"] = float(row["total_amount"]) if row["total_amount"] else 0
        row["avg_probability"] = float(row["avg_probability"]) if row["avg_probability"] else 0
        stages.append(row)

    grand_total = sum(s["total_amount"] for s in stages)
    return {"stages": stages, "grand_total": grand_total}
