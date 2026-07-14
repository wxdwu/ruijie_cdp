"""客户列表路由：提供客户筛选、筛选项、统计及 Excel 导出能力。"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.channel_classification import (
    add_customer_interaction_channel_filter,
    available_channel_options,
)
from app.services.export_service import export_customers_excel
from app.services.key_account_query import (
    KEY_ACCOUNT_SOURCE_PROJECT,
    KEY_ACCOUNT_TABLE,
    count_key_accounts,
    fetch_key_accounts,
)
from app.services.region_filter import add_region_filter, available_region_options

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/customers", tags=["customers"])


def _list_key_accounts(
    db: Session,
    *,
    keyword: Optional[str],
    industry: Optional[str],
    region: Optional[str],
    region_keyword: Optional[str],
    owner: Optional[str],
    owner_keyword: Optional[str],
    stage: Optional[str],
    intent_level: Optional[str],
    interaction_min: Optional[int],
    interaction_period: int,
    channel: Optional[str],
    sort: Optional[str],
    page: int,
    size: int,
) -> Dict[str, Any]:
    """
    查询最新一期重客名单，并补充客户 360 画像字段。

    例如：重客名单中有“甲公司”，会按名称关联其企业彩光 ICT 客户画像；
    即使画像暂未生成，该客户仍保留在重客名单结果中。
    """
    # 计数与分页查询共用同一组业务条件，保证列表总数与明细口径一致。
    query_filters = {
        "keyword": keyword,
        "industry": industry,
        "region": region,
        "region_keyword": region_keyword,
        "owner": owner,
        "owner_keyword": owner_keyword,
        "stage": stage,
        "intent_level": intent_level,
        "interaction_min": interaction_min,
        "interaction_period": interaction_period,
        "channel": channel,
    }
    total = count_key_accounts(db, **query_filters)
    items = fetch_key_accounts(
        db,
        page=page,
        size=size,
        sort=sort,
        **query_filters,
    )

    return {
        "total": total,
        "items": items,
        "filters_applied": {
            "keyword": keyword,
            "special_project": "重客",
            "industry": industry,
            "region": region,
            "region_keyword": region_keyword,
            "owner": owner,
            "owner_keyword": owner_keyword,
            "stage": stage,
            "intent_level": intent_level,
            "interaction_min": interaction_min,
            "interaction_period": interaction_period,
            "attribute": "heavy",
            "channel": channel,
            "sort": sort,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# 客户列表：按画像、互动和项目条件筛选客户
# ─────────────────────────────────────────────────────────────────────────────

@router.get("")
def list_customers(
    db: Session = Depends(get_db),
    keyword: Optional[str] = Query(None, description="按客户名称模糊搜索"),
    special_project: Optional[str] = Query(None, description="按专项标签筛选"),
    industry: Optional[str] = Query(None, description="按行业筛选"),
    region: Optional[str] = Query(None, description="按标准区域筛选"),
    region_keyword: Optional[str] = Query(None, description="按区域名称模糊搜索"),
    owner: Optional[str] = Query(None, description="按客户负责人精确筛选"),
    owner_keyword: Optional[str] = Query(None, description="按客户负责人模糊搜索"),
    stage: Optional[str] = Query(None, description="按采购阶段筛选"),
    intent_level: Optional[str] = Query(None, description="按意向等级筛选"),
    interaction_min: Optional[int] = Query(None, description="周期内最少互动次数"),
    interaction_period: int = Query(30, description="互动统计周期，单位为天"),
    attribute: Optional[str] = Query(None, description="重客属性：heavy 或 non_heavy"),
    channel: Optional[str] = Query(None, description="按发生过互动的渠道筛选"),
    sort: Optional[str] = Query(None, description="排序字段和方向，例如 intent_score desc"),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页条数，最大 100"),
) -> Dict[str, Any]:
    """返回支持多条件筛选、排序和分页的客户列表。"""
    # “重客”来自独立名单快照，查询口径不同于普通项目客户。
    if special_project == "重客":
        return _list_key_accounts(
            db,
            keyword=keyword,
            industry=industry,
            region=region,
            region_keyword=region_keyword,
            owner=owner,
            owner_keyword=owner_keyword,
            stage=stage,
            intent_level=intent_level,
            interaction_min=interaction_min,
            interaction_period=interaction_period,
            channel=channel,
            sort=sort,
            page=page,
            size=size,
        )

    where_parts: List[str] = ["1=1"]
    params: Dict[str, Any] = {}

    # 将前端筛选条件转换为参数化 SQL，覆盖客户画像的核心业务维度。
    if keyword:
        where_parts.append("customer_name LIKE :keyword")
        params["keyword"] = f"%{keyword}%"
    if special_project:
        where_parts.append("campaign_tag = :special_project")
        params["special_project"] = special_project
    if industry:
        where_parts.append("industry = :industry")
        params["industry"] = industry
    # 区域服务兼容新旧存储值，例如选择“山东”会同时匹配“山东”和“山东区域”；
    # 输入 region_keyword 时则使用模糊匹配，选择“其他”时排除全部标准区域。
    add_region_filter(
        where_parts,
        params,
        column="region",
        region=region,
        region_keyword=region_keyword,
    )
    if owner:
        # 明确选择负责人时精确匹配；仅输入搜索词时才进行模糊匹配。
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
        # 从互动明细动态统计指定周期，筛出达到最低互动次数的活跃客户。
        # 例如 period=30、interaction_min=5 表示近 30 天至少互动 5 次。
        # 子查询先按客户名称分组计数，主查询再保留满足 HAVING 条件的客户。
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
        # 客户 360 中 H 表示重客；非重客同时包含空值和其他评级。
        where_parts.append("attribute = :heavy_attribute")
        params["heavy_attribute"] = "H"
    elif attribute == "non_heavy":
        where_parts.append("(attribute IS NULL OR attribute != :heavy_attribute)")
        params["heavy_attribute"] = "H"
    add_customer_interaction_channel_filter(
        where_parts,
        params,
        customer_name_column="dws_customer_360.customer_name",
        channel=channel,
    )
    # 渠道筛选内部使用 EXISTS：客户只要任一互动明细命中所选渠道即可入选，
    # 并非只比较客户画像中的“最近互动渠道”。

    where_sql = " AND ".join(where_parts)

    # 先按同一筛选口径统计总数，供前端分页器使用。
    count_sql = text(f"SELECT COUNT(*) FROM dws_customer_360 WHERE {where_sql}")
    total: int = db.execute(count_sql, params).scalar() or 0

    # 排序字段采用白名单，默认优先展示意向分高的客户。
    sort_by = "intent_score"
    sort_order = "DESC"
    if sort:
        parts = sort.strip().split()
        allowed_sort = {
            "customer_name", "industry", "intent_score", "interaction_count_30d",
            "interaction_count_total", "last_interaction_time", "active_opp_amount",
            "won_amount", "updated_at",
        }
        if parts[0] in allowed_sort:
            sort_by = parts[0]
        if len(parts) > 1 and parts[1].upper() == "ASC":
            sort_order = "ASC"

    # 根据页码换算偏移量，只读取当前页客户画像。
    offset = (page - 1) * size
    data_sql = text(
        f"SELECT * FROM dws_customer_360 "
        f"WHERE {where_sql} "
        f"ORDER BY {sort_by} {sort_order} "
        f"LIMIT :limit OFFSET :offset"
    )
    params["limit"] = size
    params["offset"] = offset

    rows = db.execute(data_sql, params).mappings().all()
    items = [dict(r) for r in rows]

    # 原样回传本次有效筛选条件，便于前端恢复筛选状态或记录查询口径。
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
        "total": total,
        "items": items,
        "filters_applied": filters_applied,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 筛选项：选项范围与当前项目的客户范围保持一致
# ─────────────────────────────────────────────────────────────────────────────

_FILTER_OPTION_COLUMNS = (
    "industry",
    "region",
    "owner_name",
    "purchase_stage",
    "intent_level",
)


def _filter_option_rows(db: Session, special_project: Optional[str]) -> List[Any]:
    """读取指定项目客户可用的画像维度，供列表筛选器生成选项。"""
    columns = ", ".join(f"c.{column}" for column in _FILTER_OPTION_COLUMNS)
    params: Dict[str, Any] = {}
    if special_project == "重客":
        # 重客筛选项仅取最新名单，并关联其来源项目下的客户画像。
        # MAX(time) 锁定最新批次；LEFT JOIN 保留尚无客户 360 画像的重客，
        # 这些客户的画像维度为空，后续生成选项时会自动忽略。
        sql = text(
            f"""
            SELECT {columns}
            FROM {KEY_ACCOUNT_TABLE} ka
            LEFT JOIN dws_customer_360 c
              ON c.customer_name = ka.`重客名称`
             AND c.campaign_tag = :filter_source_project
            WHERE ka.`time` = (SELECT MAX(`time`) FROM {KEY_ACCOUNT_TABLE})
            """
        )
        params["filter_source_project"] = KEY_ACCOUNT_SOURCE_PROJECT
    else:
        where_sql = ""
        if special_project:
            # 例如专项为“制造业活动”，只从该专项客户中提取行业、区域等候选值。
            where_sql = "WHERE c.campaign_tag = :filter_special_project"
            params["filter_special_project"] = special_project
        sql = text(f"SELECT {columns} FROM dws_customer_360 c {where_sql}")
    return db.execute(sql, params).mappings().all()


def _facet_values(rows: List[Any], column: str) -> List[str]:
    """清洗、去重并排序单个画像维度的候选值。"""
    return sorted({str(row.get(column)).strip() for row in rows if row.get(column) not in (None, "")})


def _channel_option_rows(db: Session, special_project: Optional[str]) -> List[Any]:
    """按项目客户范围读取真实发生过互动的渠道。"""
    params: Dict[str, Any] = {}
    if special_project == "重客":
        # 只统计最新重客名单中客户实际出现过的互动渠道。
        sql = text(
            f"""
            SELECT DISTINCT interaction.channel
            FROM dws_interaction_detail interaction
            INNER JOIN {KEY_ACCOUNT_TABLE} ka
              ON ka.`重客名称` = interaction.customer_name
             AND ka.`time` = (SELECT MAX(`time`) FROM {KEY_ACCOUNT_TABLE})
            WHERE interaction.channel IS NOT NULL AND TRIM(interaction.channel) != ''
            """
        )
    elif special_project:
        # 普通专项先通过客户 360 圈定客户，再关联互动明细提取渠道。
        sql = text(
            """
            SELECT DISTINCT interaction.channel
            FROM dws_interaction_detail interaction
            INNER JOIN dws_customer_360 c ON c.customer_name = interaction.customer_name
            WHERE c.campaign_tag = :channel_special_project
              AND interaction.channel IS NOT NULL AND TRIM(interaction.channel) != ''
            """
        )
        params["channel_special_project"] = special_project
    else:
        # 未指定专项时返回全量客户互动中出现过的渠道。
        sql = text(
            """
            SELECT DISTINCT interaction.channel
            FROM dws_interaction_detail interaction
            WHERE interaction.channel IS NOT NULL AND TRIM(interaction.channel) != ''
            """
        )
    return db.execute(sql, params).mappings().all()


@router.get("/filter-options")
def get_filter_options(
    db: Session = Depends(get_db),
    special_project: Optional[str] = Query(None, description="将筛选项限定在指定专项客户范围内"),
) -> Dict[str, List[str]]:
    """返回当前客户范围内可用的行业、区域、负责人等筛选项。"""
    rows = _filter_option_rows(db, special_project)
    channel_rows = _channel_option_rows(db, special_project)
    return {
        "industries": _facet_values(rows, "industry"),
        "regions": available_region_options(row.get("region") for row in rows),
        "owners": _facet_values(rows, "owner_name"),
        "stages": _facet_values(rows, "purchase_stage"),
        "intent_levels": _facet_values(rows, "intent_level"),
        "channels": available_channel_options(row.get("channel") for row in channel_rows),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 客户统计：汇总各客户的联系人及互动规模
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/statistics")
def get_customer_statistics(
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    获取每个客户的联系人总数和互动数量统计.

    返回所有客户的统计信息，包括：
    - customer_name: 客户名称
    - contact_count: 联系人总数
    - interaction_count_total: 总互动数量
    - interaction_count_30d: 近30天互动数量
    - intent_level: 意向等级
    - purchase_stage: 采购阶段

    同时返回汇总统计信息（total_contacts, total_interactions）
    """
    # 客户 360 已完成联系人和互动聚合，可直接按总互动量排序。
    # 例如某客户 contact_count=10、interaction_count_total=100，代表已识别
    # 10 名联系人、累计沉淀 100 条互动；本接口不再扫描联系人和互动明细表。
    sql = text("""
        SELECT
            customer_name,
            contact_count,
            interaction_count_total,
            interaction_count_30d,
            intent_level,
            purchase_stage
        FROM dws_customer_360
        ORDER BY interaction_count_total DESC
    """)

    rows = db.execute(sql).mappings().all()
    items = [dict(r) for r in rows]

    # 汇总全部客户的联系人和互动量，供统计卡片展示。
    total_contacts = sum(item.get("contact_count", 0) or 0 for item in items)
    total_interactions = sum(item.get("interaction_count_total", 0) or 0 for item in items)

    return {
        "items": items,
        "total": len(items),
        "summary": {
            "total_contacts": total_contacts,
            "total_interactions": total_interactions,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# 单客户统计：按名称模糊查找联系人及互动规模
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/statistics/by-name")
def get_customer_statistics_by_name(
    customer_name: str = Query(..., description="客户名称（支持模糊匹配）"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    根据客户名称查询联系人和互动统计数据.

    通过客户名称（支持模糊匹配）查询该客户的：
    - contact_count: 联系人总数
    - interaction_count_total: 总互动数量

    返回格式：
    {
        "status": "success",
        "timestamp": "2026-06-18T10:30:00",
        "data": {
            "customer_name": "山东魏桥创业集团有限公司",
            "contact_count": 10,
            "interaction_count_total": 1092
        }
    }
    """
    # 兼容用户输入简称或名称片段，例如输入“魏桥”可匹配完整公司名称；
    # 当前接口只需要一个详情对象，因此通过 LIMIT 1 返回首条匹配客户。
    sql = text("""
        SELECT
            customer_name,
            contact_count,
            interaction_count_total
        FROM dws_customer_360
        WHERE customer_name LIKE :customer_name
        LIMIT 1
    """)

    params = {"customer_name": f"%{customer_name}%"}
    rows = db.execute(sql, params).mappings().all()

    # 响应携带查询时间，便于调用方标记统计结果的新鲜度。
    from datetime import datetime
    timestamp = datetime.now().isoformat()

    if not rows:
        return {
            "status": "not_found",
            "timestamp": timestamp,
            "data": None,
            "message": f"未找到客户: {customer_name}",
        }

    result = dict(rows[0])

    return {
        "status": "success",
        "timestamp": timestamp,
        "data": {
            "customer_name": result.get("customer_name"),
            "contact_count": result.get("contact_count", 0),
            "interaction_count_total": result.get("interaction_count_total", 0),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# 客户导出：按列表筛选口径生成 Excel
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/export")
def export_customers(
    db: Session = Depends(get_db),
    keyword: Optional[str] = Query(None, description="按客户名称模糊搜索"),
    special_project: Optional[str] = Query(None, description="按专项标签筛选"),
    industry: Optional[str] = Query(None, description="按行业筛选"),
    region: Optional[str] = Query(None, description="按标准区域筛选"),
    region_keyword: Optional[str] = Query(None, description="按区域名称模糊搜索"),
    owner: Optional[str] = Query(None, description="按客户负责人精确筛选"),
    owner_keyword: Optional[str] = Query(None, description="按客户负责人模糊搜索"),
    stage: Optional[str] = Query(None, description="按采购阶段筛选"),
    intent_level: Optional[str] = Query(None, description="按意向等级筛选"),
    interaction_min: Optional[int] = Query(None, description="周期内最少互动次数"),
    interaction_period: int = Query(30, description="互动统计周期，单位为天"),
    attribute: Optional[str] = Query(None, description="重客属性：heavy 或 non_heavy"),
    channel: Optional[str] = Query(None, description="按发生过互动的渠道筛选"),
    sort: Optional[str] = Query(None, description="排序字段和方向，例如 intent_score desc"),
) -> Response:
    """将筛选后的完整客户列表导出为 Excel 文件。"""
    # 与列表接口保持相同的排序白名单和默认排序。
    sort_by = "intent_score"
    sort_order = "DESC"
    if sort:
        parts = sort.strip().split()
        allowed_sort = {
            "customer_name", "industry", "intent_score", "interaction_count_30d",
            "interaction_count_total", "last_interaction_time", "active_opp_amount",
            "won_amount", "updated_at",
        }
        if parts[0] in allowed_sort:
            sort_by = parts[0]
        if len(parts) > 1 and parts[1].upper() == "ASC":
            sort_order = "ASC"

    # 导出服务复用全部业务筛选条件，并负责生成工作簿字节流。
    excel_bytes = export_customers_excel(
        db,
        keyword=keyword,
        special_project=special_project,
        industry=industry,
        region=region,
        region_keyword=region_keyword,
        owner=owner,
        owner_keyword=owner_keyword,
        stage=stage,
        intent_level=intent_level,
        interaction_min=interaction_min,
        interaction_period=interaction_period,
        attribute=attribute,
        channel=channel,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=customers_export.xlsx",
        },
    )
