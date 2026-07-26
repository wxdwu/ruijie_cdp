"""
客户 360 查询服务。

集中维护 dws_customer_360 的列表查询与筛选条件构建，供
customer_list 路由、export_service 导出等复用，避免过滤逻辑散落多份、重复实现。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.common.channel_classification import (
    add_customer_interaction_channel_filter,
    available_channel_options,
)
from app.services.common.region_filter import (
    add_region_filter,
    available_region_options,
)
from app.services.customer.key_account_query import (
    KEY_ACCOUNT_SOURCE_PROJECT,
    KEY_ACCOUNT_TABLE,
    list_key_accounts,
)
from app.services.utils import add_in_filter as _add_in_filter
from app.config import settings

logger = logging.getLogger(__name__)

# 合法公司名判定：customer_name 包含任一企业特征词即视为有效公司名（保守口径，
# 仅剔除明显非法/用户名类记录，避免误删真实公司）。正则用于 REGEXP 匹配。
VALID_COMPANY_REGEX = (
    "公司|集团|股份|有限公司|有限责任公司|企业|厂|局|所|院|银行|保险|证券|"
    "医院|学校|大学|学院|电视台|出版社|报社|协会|基金会|合作社|商行|门店|"
    "中心|科技|网络|技术|实业|控股|投资|管理|咨询|电子|信息|能源|医疗|"
    "生物|教育|文化|传媒|贸易|物流|建设|工程|房地产|置业|酒店|旅游|食品|"
    "服饰|汽车|机械|化工|材料|环境|智能|数据|软件|通信|金融|基金|租赁|"
    "供应链|电子商务"
)


def _load_filter_name_set(db: Session, table: str) -> List[str]:
    """从指定表读取一列公司名（表需含 customer_name 列）。

    表不存在或列缺失时返回空列表（对应子筛选变为无操作），不抛异常。
    """
    try:
        rows = db.execute(text(f"SELECT customer_name FROM {table}")).fetchall()
        return [r[0] for r in rows if r[0]]
    except Exception as exc:  # 表未创建等
        logger.warning("读取筛选表 %s 失败（已忽略）：%s", table, exc)
        return []


def _apply_customer_filters(
    where_parts: List[str],
    params: Dict[str, Any],
    db: Session,
) -> None:
    """按配置开关追加客户列表筛选条件（当前默认全部禁用）。

    规则（均受“保命条件”保护：有联系人/互动的行始终保留，避免误删有效数据）：
    - 非法公司名/用户名：customer_name 不含任何企业特征词且无联系人与互动的行被剔除。
    - 黑名单（精确）：命中的公司名被剔除（当前默认禁用）。
    - 白名单（允许名单）：仅白名单内公司名保留（当前默认禁用）。
    """
    if not settings.CUSTOMER_FILTER_ENABLED:
        return

    # 保命条件：有联系人或有互动的行始终保留
    keep_data = "(contact_count > 0 OR interaction_count_total > 0)"

    # 1) 非法公司名 / 用户名剔除
    if settings.CUSTOMER_FILTER_ILLEGAL_ENABLED:
        where_parts.append(
            f"(customer_name REGEXP :valid_company_regex OR {keep_data})"
        )
        params["valid_company_regex"] = VALID_COMPANY_REGEX

    # 2) 黑名单（精确匹配，当前默认禁用）
    if settings.CUSTOMER_FILTER_BLACKLIST_ENABLED:
        blacklist = _load_filter_name_set(db, "company_blacklist")
        if blacklist:
            ph = ", ".join(f":bl_{i}" for i in range(len(blacklist)))
            for i, name in enumerate(blacklist):
                params[f"bl_{i}"] = name
            where_parts.append(f"(customer_name NOT IN ({ph}) OR {keep_data})")

    # 3) 白名单（允许名单，当前默认禁用）
    if settings.CUSTOMER_FILTER_WHITELIST_ENABLED:
        whitelist = _load_filter_name_set(db, "company_whitelist")
        if whitelist:
            ph = ", ".join(f":wl_{i}" for i in range(len(whitelist)))
            for i, name in enumerate(whitelist):
                params[f"wl_{i}"] = name
            where_parts.append(f"(customer_name IN ({ph}) OR {keep_data})")

# 允许排序的字段（白名单，防止 SQL 注入）
ALLOWED_SORT = {
    "customer_name", "industry", "intent_score", "interaction_count_30d",
    "interaction_count_total", "last_interaction_time", "active_opp_amount",
    "won_amount", "updated_at",
}


def parse_sort(sort: Optional[str]) -> tuple[str, str]:
    """解析排序串（"字段 [ASC|DESC]"），返回 (sort_by, sort_order)。

    非法字段回退到 intent_score，非法方向回退到 DESC，防止 SQL 注入。
    供列表查询与导出复用，统一排序解析口径。
    """
    sort_by = "intent_score"
    sort_order = "DESC"
    if sort:
        parts = sort.strip().split()
        if parts and parts[0] in ALLOWED_SORT:
            sort_by = parts[0]
        if len(parts) > 1 and parts[1].upper() == "ASC":
            sort_order = "ASC"
    return sort_by, sort_order


def list_customers(
    db: Session,
    *,
    keyword: Optional[List[str]] = None,
    special_project: Optional[List[str]] = None,
    industry: Optional[List[str]] = None,
    region: Optional[List[str]] = None,
    region_keyword: Optional[str] = None,
    owner: Optional[List[str]] = None,
    owner_keyword: Optional[str] = None,
    stage: Optional[str] = None,
    intent_level: Optional[str] = None,
    interaction_min: Optional[int] = None,
    interaction_period: int = 30,
    attribute: Optional[str] = None,
    channel: Optional[List[str]] = None,
    sort: Optional[str] = None,
    page: int = 1,
    size: int = 20,
) -> Dict[str, Any]:
    """客户列表查询编排：按专项决定数据源。

    "重客" 专项走重客快照（key_account_query），其余走 dws_customer_360。
    路由层只需委托本函数，无需感知数据源切换这一领域规则。
    """
    special_project = special_project or []
    if len(special_project) == 1 and special_project[0] == "重客":
        return list_key_accounts(
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

    return get_customer_list(
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
        sort=sort,
        page=page,
        page_size=size,
    )


def get_customer_list(
    db: Session,
    *,
    keyword: Optional[List[str]] = None,
    special_project: Optional[List[str]] = None,
    industry: Optional[List[str]] = None,
    region: Optional[List[str]] = None,
    region_keyword: Optional[str] = None,
    owner: Optional[List[str]] = None,
    owner_keyword: Optional[str] = None,
    stage: Optional[str] = None,
    intent_level: Optional[str] = None,
    interaction_min: Optional[int] = None,
    interaction_period: int = 30,
    attribute: Optional[str] = None,
    channel: Optional[List[str]] = None,
    sort: str = "intent_score DESC",
    page: int = 1,
    page_size: int = 50,
) -> Dict[str, Any]:
    """查询 dws_customer_360，支持多维度（含多选）筛选、排序与分页。

    作为客户列表 / 导出等场景的唯一查询来源，统一过滤逻辑。
    专项、行业、区域、负责人、互动方式均支持多选（IN 过滤）。
    返回 {items, total, page, page_size, filters_applied}。
    """
    where_parts: List[str] = ["1=1"]
    params: Dict[str, Any] = {}

    # 客户关键词：多选时按 customer_name 精确 IN 过滤
    _add_in_filter(where_parts, params, "customer_name", keyword, "keyword")
    # 专项：多选时按 campaign_tag IN 过滤
    _add_in_filter(where_parts, params, "campaign_tag", special_project, "special_project")
    # 行业：多选 IN 过滤
    _add_in_filter(where_parts, params, "industry", industry, "industry")
    # 区域：多选（兼容「广东」与「广东区域」两种写法）
    add_region_filter(
        where_parts, params,
        column="region", region=region, region_keyword=region_keyword,
    )
    # 负责人：多选 IN 过滤
    if owner:
        owner_placeholders: List[str] = []
        for index, value in enumerate(owner):
            key = f"owner_{index}"
            params[key] = value
            owner_placeholders.append(f":{key}")
        where_parts.append(f"owner_name IN ({', '.join(owner_placeholders)})")
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
    # 渠道筛选（基于互动明细 EXISTS 子查询，支持多选）
    add_customer_interaction_channel_filter(
        where_parts, params,
        customer_name_column="dws_customer_360.customer_name",
        channel=channel,
    )

    # 客户列表筛选（默认禁用，待数据对齐后开启；见 config.CUSTOMER_FILTER_*）
    _apply_customer_filters(where_parts, params, db)

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


# ─────────────────────────────────────────────────────────────────────────────
# 筛选选项 / 统计（原 customer_list 路由内的裸 SQL 逻辑，下沉到 service 层）
# ─────────────────────────────────────────────────────────────────────────────

_FILTER_OPTION_COLUMNS = (
    "industry",
    "region",
    "owner_name",
    "purchase_stage",
    "intent_level",
)


def _filter_option_rows(db: Session, special_projects: List[str]) -> List[Any]:
    """返回所选专项客户群体的合并列（用于下拉选项去重）。"""
    columns = ", ".join(f"c.{column}" for column in _FILTER_OPTION_COLUMNS)
    rows: List[Any] = []
    # 重客：来自重客快照表，客户名称优先取重客名称（未进入彩光的重客也能作为候选项）
    if "重客" in special_projects:
        ka_sql = text(
            f"""
            SELECT {columns}, COALESCE(ka.`重客名称`, c.customer_name) AS customer_name
            FROM {KEY_ACCOUNT_TABLE} ka
            LEFT JOIN dws_customer_360 c
              ON c.customer_name = ka.`重客名称`
             AND c.campaign_tag = :filter_source_project
            WHERE ka.`time` = (SELECT MAX(`time`) FROM {KEY_ACCOUNT_TABLE})
            """
        )
        rows.extend(
            db.execute(ka_sql, {"filter_source_project": KEY_ACCOUNT_SOURCE_PROJECT}).mappings().all()
        )
    # 其余专项：来自 dws_customer_360
    others = [p for p in special_projects if p != "重客"]
    if others:
        other_sql = text(
            f"SELECT {columns}, c.customer_name AS customer_name FROM dws_customer_360 c "
            f"WHERE c.campaign_tag IN :filter_other_projects"
        )
        rows.extend(
            db.execute(other_sql, {"filter_other_projects": tuple(others)}).mappings().all()
        )
    # 未选任何专项：返回全部客户
    if not special_projects:
        all_sql = text(f"SELECT {columns}, c.customer_name AS customer_name FROM dws_customer_360 c")
        rows.extend(db.execute(all_sql).mappings().all())
    return rows


def _facet_values(rows: List[Any], column: str) -> List[str]:
    return sorted({str(row.get(column)).strip() for row in rows if row.get(column) not in (None, "")})


def _channel_option_rows(db: Session, special_projects: List[str]) -> List[Any]:
    params: Dict[str, Any] = {}
    clauses: List[str] = []
    if "重客" in special_projects:
        clauses.append(
            f"""
            SELECT DISTINCT interaction.channel
            FROM dws_interaction_detail interaction
            INNER JOIN {KEY_ACCOUNT_TABLE} ka
              ON ka.`重客名称` = interaction.customer_name
             AND ka.`time` = (SELECT MAX(`time`) FROM {KEY_ACCOUNT_TABLE})
            WHERE interaction.channel IS NOT NULL AND TRIM(interaction.channel) != ''
            """
        )
    others = [p for p in special_projects if p != "重客"]
    if others:
        clauses.append(
            """
            SELECT DISTINCT interaction.channel
            FROM dws_interaction_detail interaction
            INNER JOIN dws_customer_360 c ON c.customer_name = interaction.customer_name
            WHERE c.campaign_tag IN :channel_other_projects
              AND interaction.channel IS NOT NULL AND TRIM(interaction.channel) != ''
            """
        )
        params["channel_other_projects"] = tuple(others)
    if not special_projects:
        clauses.append(
            """
            SELECT DISTINCT interaction.channel
            FROM dws_interaction_detail interaction
            WHERE interaction.channel IS NOT NULL AND TRIM(interaction.channel) != ''
            """
        )
    if not clauses:
        return []
    sql = text(" UNION ".join(clauses))
    return db.execute(sql, params).mappings().all()


def get_filter_options(
    db: Session,
    special_project: Optional[List[str]] = None,
) -> Dict[str, List[str]]:
    """返回与列表同口径的客户群体筛选维度（行业/区域/负责人/名称/阶段/意向/渠道）。"""
    special_project = special_project or []
    rows = _filter_option_rows(db, special_project)
    channel_rows = _channel_option_rows(db, special_project)
    return {
        "industries": _facet_values(rows, "industry"),
        "regions": available_region_options(row.get("region") for row in rows),
        "owners": _facet_values(rows, "owner_name"),
        "keywords": _facet_values(rows, "customer_name"),
        "stages": _facet_values(rows, "purchase_stage"),
        "intent_levels": _facet_values(rows, "intent_level"),
        "channels": available_channel_options(row.get("channel") for row in channel_rows),
    }


def get_customer_statistics(db: Session) -> Dict[str, Any]:
    """返回每个客户的联系人数与互动数量统计，以及汇总信息。"""
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


def get_customer_statistics_by_name(db: Session, customer_name: str) -> Dict[str, Any]:
    """按客户名称（模糊匹配）查询联系人与互动统计。"""
    sql = text("""
        SELECT
            customer_name,
            contact_count,
            interaction_count_total
        FROM dws_customer_360
        WHERE customer_name LIKE :customer_name
        LIMIT 1
    """)
    rows = db.execute(sql, {"customer_name": f"%{customer_name}%"}).mappings().all()
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
# 客户详情（原 customer_detail 路由内的裸 SQL 逻辑，下沉到 service 层）
# ─────────────────────────────────────────────────────────────────────────────

class CustomerNotFound(Exception):
    """客户不存在时由 service 抛出，由路由层转换为 404。"""


def get_customer_name(db: Session, customer_id: str) -> str:
    """按 id 查询 customer_name，不存在抛出 CustomerNotFound。"""
    row = db.execute(
        text("SELECT customer_name FROM dws_customer_360 WHERE id = :cid"),
        {"cid": customer_id},
    ).fetchone()
    if not row:
        raise CustomerNotFound(customer_id)
    return row[0]


def get_customer_detail(db: Session, customer_id: str) -> Dict[str, Any]:
    """返回客户 360 详情，并补充近 30 天互动数与最近拜访信息。"""
    row = db.execute(
        text("SELECT * FROM dws_customer_360 WHERE id = :cid"),
        {"cid": customer_id},
    ).mappings().fetchone()
    if not row:
        raise CustomerNotFound(customer_id)

    result = dict(row)
    interaction_count_30d = db.execute(
        text(
            "SELECT COUNT(*) FROM dws_interaction_detail "
            "WHERE customer_name = :cname "
            "  AND event_time >= DATE_SUB(NOW(), INTERVAL 30 DAY)"
        ),
        {"cname": result.get("customer_name")},
    ).scalar() or 0
    result["interaction_count_30d"] = int(interaction_count_30d)

    visit_row = db.execute(
        text(
            "SELECT MAX(last_visit_time) AS last_visit_time, "
            "       MIN(not_visit_days) AS no_visit_days "
            "FROM ods_crm_contact_day "
            "WHERE customer_name = :cname"
        ),
        {"cname": result.get("customer_name")},
    ).mappings().fetchone()

    if visit_row:
        result["last_visit_time"] = visit_row.get("last_visit_time")
        result["no_visit_days"] = visit_row.get("no_visit_days")
    else:
        result["last_visit_time"] = None
        result["no_visit_days"] = None

    return result


def get_customer_contacts(db: Session, customer_id: str) -> Dict[str, Any]:
    """返回客户联系人列表（优先 dws_contact_360，缺失时回退 dws_contact_mapping）。"""
    customer_row = db.execute(
        text(
            "SELECT customer_name, purchase_stage, intent_level "
            "FROM dws_customer_360 WHERE id = :cid"
        ),
        {"cid": customer_id},
    ).mappings().fetchone()
    if not customer_row:
        raise CustomerNotFound(customer_id)

    customer_name = customer_row["customer_name"]

    rows = db.execute(
        text(
            "SELECT c.id, c.customer_id, c.contact_name, c.mobile, c.email, "
            "       c.department, c.position, c.purchase_role, c.role_category, "
            "       c.interaction_count, c.interaction_count_30d, "
            "       c.last_interaction_time, c.top_content_types, "
            "       c.product_interests, c.activity_level, c.intent_level, "
            "       c.lead_stage, c.source_tables, c.linkflow_contact_id, "
            "       COALESCE(c.lead_stage, :customer_stage) AS purchase_stage, "
            "       :customer_stage AS customer_purchase_stage, "
            "       COALESCE(c.intent_level, :customer_intent_level) AS display_intent_level, "
            "       :customer_intent_level AS customer_intent_level, "
            "       CAST(COALESCE(hv.high_value_count, 0) AS SIGNED) AS high_value_count, "
            "       pc.channel AS preferred_channel "
            "FROM dws_contact_360 c "
            "LEFT JOIN ( "
            "    SELECT contact_name, mobile, "
            "           SUM(CASE WHEN is_high_value = 1 THEN 1 ELSE 0 END) AS high_value_count "
            "    FROM dws_interaction_detail "
            "    WHERE customer_name = :cname "
            "    GROUP BY contact_name, mobile "
            ") hv ON hv.contact_name <=> c.contact_name "
            "     AND hv.mobile <=> c.mobile "
            "LEFT JOIN ( "
            "    SELECT contact_name, mobile, channel "
            "    FROM ( "
            "        SELECT contact_name, mobile, channel, "
            "               ROW_NUMBER() OVER ( "
            "                   PARTITION BY contact_name, mobile "
            "                   ORDER BY COUNT(*) DESC, MAX(event_time) DESC "
            "               ) AS rn "
            "        FROM dws_interaction_detail "
            "        WHERE customer_name = :cname "
            "          AND channel IS NOT NULL AND channel != '' "
            "        GROUP BY contact_name, mobile, channel "
            "    ) preferred_ranked "
            "    WHERE rn = 1 "
            ") pc ON pc.contact_name <=> c.contact_name "
            "     AND pc.mobile <=> c.mobile "
            "WHERE c.customer_id = :cid "
            "ORDER BY c.interaction_count DESC, c.contact_name"
        ),
        {
            "cid": customer_id,
            "cname": customer_name,
            "customer_stage": customer_row.get("purchase_stage"),
            "customer_intent_level": customer_row.get("intent_level"),
        },
    ).mappings().all()

    if not rows:
        rows = db.execute(
            text(
                "SELECT cm.id, cm.contact_name, cm.mobile, cm.email, "
                "       cm.department, cm.position, cm.purchase_role, "
                "       cm.role_category, cm.source_table, "
                "       JSON_ARRAY(cm.source_table) AS source_tables, "
                "       cm.linkflow_contact_id, "
                "       0 AS interaction_count, 0 AS interaction_count_30d, "
                "       NULL AS last_interaction_time, NULL AS top_content_types, "
                "       NULL AS product_interests, NULL AS activity_level, "
                "       NULL AS intent_level, NULL AS lead_stage, "
                "       :customer_stage AS purchase_stage, "
                "       :customer_stage AS customer_purchase_stage, "
                "       :customer_intent_level AS display_intent_level, "
                "       :customer_intent_level AS customer_intent_level, "
                "       CAST(COALESCE(hv.high_value_count, 0) AS SIGNED) AS high_value_count, "
                "       pc.channel AS preferred_channel "
                "FROM dws_contact_mapping cm "
                "LEFT JOIN ( "
                "    SELECT contact_name, mobile, "
                "           SUM(CASE WHEN is_high_value = 1 THEN 1 ELSE 0 END) AS high_value_count "
                "    FROM dws_interaction_detail "
                "    WHERE customer_name = :cname "
                "    GROUP BY contact_name, mobile "
                ") hv ON hv.contact_name <=> cm.contact_name "
                "     AND hv.mobile <=> cm.mobile "
                "LEFT JOIN ( "
                "    SELECT contact_name, mobile, channel "
                "    FROM ( "
                "        SELECT contact_name, mobile, channel, "
                "               ROW_NUMBER() OVER ( "
                "                   PARTITION BY contact_name, mobile "
                "                   ORDER BY COUNT(*) DESC, MAX(event_time) DESC "
                "               ) AS rn "
                "        FROM dws_interaction_detail "
                "        WHERE customer_name = :cname "
                "          AND channel IS NOT NULL AND channel != '' "
                "        GROUP BY contact_name, mobile, channel "
                "    ) preferred_ranked "
                "    WHERE rn = 1 "
                ") pc ON pc.contact_name <=> cm.contact_name "
                "     AND pc.mobile <=> cm.mobile "
                "WHERE cm.customer_name = :cname "
                "ORDER BY cm.contact_name"
            ),
            {
                "cname": customer_name,
                "customer_stage": customer_row.get("purchase_stage"),
                "customer_intent_level": customer_row.get("intent_level"),
            },
        ).mappings().all()

    return {
        "customer_id": customer_id,
        "customer_name": customer_name,
        "contacts": [dict(r) for r in rows],
        "total": len(rows),
    }


def get_customer_interactions(
    db: Session,
    customer_id: str,
    limit: int = 50,
) -> Dict[str, Any]:
    """返回客户互动时间线（按 event_time 倒序）。"""
    customer_name = get_customer_name(db, customer_id)
    rows = db.execute(
        text(
            "SELECT * FROM dws_interaction_detail "
            "WHERE customer_name = :cname "
            "ORDER BY event_time DESC "
            "LIMIT :lim"
        ),
        {"cname": customer_name, "lim": limit},
    ).mappings().all()
    return {
        "customer_id": customer_id,
        "customer_name": customer_name,
        "interactions": [dict(r) for r in rows],
        "total": len(rows),
    }


def get_customer_opportunities(db: Session, customer_id: str) -> Dict[str, Any]:
    """返回客户 CRM 商机（按 create_date 倒序）。"""
    customer_name = get_customer_name(db, customer_id)
    rows = db.execute(
        text(
            "SELECT * FROM ods_crm_opportunity_day "
            "WHERE customer_name = :cname "
            "ORDER BY create_date DESC"
        ),
        {"cname": customer_name},
    ).mappings().all()
    return {
        "customer_id": customer_id,
        "customer_name": customer_name,
        "opportunities": [dict(r) for r in rows],
        "total": len(rows),
    }


def build_customer_ai_insight(db: Session, customer_id: str) -> Dict[str, Any]:
    """构建客户 AI 洞察（规则结论 + 优先联系人推荐）。"""
    from app.services.ai.contact_recommend import recommend_priority_contacts

    customer_name = get_customer_name(db, customer_id)
    customer_row = db.execute(
        text("SELECT * FROM dws_customer_360 WHERE id = :cid"),
        {"cid": customer_id},
    ).mappings().fetchone()
    if not customer_row:
        raise CustomerNotFound(customer_id)

    customer = dict(customer_row)

    interaction_count = db.execute(
        text(
            "SELECT COUNT(*) FROM dws_interaction_detail "
            "WHERE customer_name = :cname "
            "  AND event_time >= DATE_SUB(NOW(), INTERVAL 3 MONTH)"
        ),
        {"cname": customer_name},
    ).scalar() or 0

    opp_count = int(customer.get("funnel_opp_count") or 0)

    business_conclusion: List[str] = []
    intent_level = customer.get("intent_level", "")
    if intent_level == "高":
        business_conclusion.append("客户处于高意向阶段，建议重点跟进")
    elif intent_level == "中":
        business_conclusion.append("客户处于中意向阶段，需要持续培育")
    elif intent_level == "低":
        business_conclusion.append("客户意向度较低，建议先进行市场教育")

    if interaction_count > 10:
        business_conclusion.append(f"客户近3个月互动活跃（{interaction_count}次），购买信号强烈")
    elif interaction_count > 0:
        business_conclusion.append(f"客户近3个月有{interaction_count}次互动记录，保持跟进")
    else:
        business_conclusion.append("客户近3个月暂无互动记录，建议主动触达")

    if opp_count > 0:
        business_conclusion.append(f"客户现有{opp_count}个漏斗内商机，需重点维护")

    evidence = {
        "intent_score": customer.get("intent_score", 0),
        "intent_level": intent_level,
        "interaction_count": interaction_count,
        "opportunity_count": opp_count,
        "contact_count": customer.get("contact_count", 0),
        "mobile_count": customer.get("mobile_count", 0),
        "last_interaction_time": str(customer.get("last_interaction_time", "")),
        "last_interaction_channel": customer.get("last_interaction_channel", ""),
    }

    priority_result = recommend_priority_contacts(
        db=db,
        customer_id=customer_id,
        customer_name=customer_name,
        top_n=3,
    )

    return {
        "business_conclusion": business_conclusion,
        "evidence": evidence,
        "recommendation": priority_result.get("recommendation"),
        "recommendations": priority_result.get("recommendations", []),
        "total_candidates": priority_result.get("total_candidates", 0),
        "source": priority_result.get("source", "rule"),
    }
