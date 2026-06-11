"""
Export service – generates Excel files for customer data downloads.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.services.customer_service import get_customer_list

logger = logging.getLogger(__name__)

# Column definitions: (db_field, header_label, width)
_EXPORT_COLUMNS: List[tuple] = [
    ("customer_id",           "客户ID",       18),
    ("customer_name",         "客户名称",     25),
    ("company_name",          "公司名称",     30),
    ("industry",              "行业",         15),
    ("region",                "区域",         12),
    ("total_interactions",    "互动总数",     12),
    ("last_interaction_time", "最近互动时间", 20),
    ("email_count",           "邮件次数",     12),
    ("web_count",             "网站次数",     12),
    ("wechat_count",          "微信次数",     12),
    ("phone_count",           "电话次数",     12),
    ("event_count",           "活动次数",     12),
    ("active_days_30d",       "30天活跃天数", 14),
    ("active_days_90d",       "90天活跃天数", 14),
    ("engagement_score",      "参与度评分",   14),
    ("opportunity_amount",    "商机金额",     15),
    ("opportunity_count",     "商机数量",     12),
    ("won_amount",            "赢单金额",     15),
    ("tags",                  "标签",         25),
]


def export_customers_excel(
    db: Session,
    *,
    keyword: Optional[str] = None,
    industry: Optional[str] = None,
    region: Optional[str] = None,
    min_engagement_score: Optional[float] = None,
    max_engagement_score: Optional[float] = None,
    min_opportunity_amount: Optional[float] = None,
    active_days_30d_min: Optional[int] = None,
    tags: Optional[List[str]] = None,
    sort_by: str = "engagement_score",
    sort_order: str = "DESC",
    max_rows: int = 10_000,
) -> bytes:
    """Generate an Excel (.xlsx) workbook containing the filtered customer list.

    Args:
        db: Database session.
        **filters: Same filters as get_customer_list().
        max_rows: Safety cap to avoid huge exports.

    Returns:
        Raw bytes of the .xlsx file (ready to stream as a Response).
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill, Border, Side

    # Fetch data (single page, up to max_rows)
    result = get_customer_list(
        db,
        keyword=keyword,
        industry=industry,
        region=region,
        min_engagement_score=min_engagement_score,
        max_engagement_score=max_engagement_score,
        min_opportunity_amount=min_opportunity_amount,
        active_days_30d_min=active_days_30d_min,
        tags=tags,
        sort_by=sort_by,
        sort_order=sort_order,
        page=1,
        page_size=max_rows,
    )

    items = result["items"]
    wb = Workbook()
    ws = wb.active
    ws.title = "客户360数据"

    # ── Header styling ──────────────────────────────────────────────────────
    header_font = Font(name="微软雅黑", bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9"),
    )

    # Write headers
    for col_idx, (field, label, width) in enumerate(_EXPORT_COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=label)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border
        ws.column_dimensions[cell.column_letter].width = width

    # ── Data rows ───────────────────────────────────────────────────────────
    data_font = Font(name="微软雅黑", size=10)
    data_align = Alignment(vertical="center")

    for row_idx, item in enumerate(items, start=2):
        for col_idx, (field, _label, _width) in enumerate(_EXPORT_COLUMNS, start=1):
            value = item.get(field, "")

            # Format special fields
            if field == "tags" and isinstance(value, list):
                value = ", ".join(value)
            elif field in ("engagement_score", "opportunity_amount", "won_amount"):
                try:
                    value = float(value) if value else 0
                except (ValueError, TypeError):
                    value = 0
            elif isinstance(value, datetime):
                value = value.strftime("%Y-%m-%d %H:%M")

            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.font = data_font
            cell.alignment = data_align
            cell.border = thin_border

    # Freeze the header row
    ws.freeze_panes = "A2"

    # Auto-filter
    last_col = ws.cell(row=1, column=len(_EXPORT_COLUMNS)).column_letter
    ws.auto_filter.ref = f"A1:{last_col}{len(items) + 1}"

    # Write to bytes buffer
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    logger.info(
        "Exported %d customers to Excel (%d bytes)",
        len(items), buf.getbuffer().nbytes,
    )
    return buf.getvalue()
