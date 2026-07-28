"""
客户 360 查询服务。

集中维护 dws_customer_360 的列表查询与筛选条件构建，供
customer_list 路由、export_service 导出等复用，避免过滤逻辑散落多份、重复实现。
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, PendingRollbackError
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
from app.services.common.company_name_clean import (
    clean_company_symbols,
    is_valid_company_name,
)
from app.services.common.company_filter import (
    build_customer_filter,
    build_company_name_preprocess,
)
from app.services.company_dedup.company_merge import (
    ensure_merge_map_table,
    get_member_names,
    resolve_customer,
)
from app.config import settings

logger = logging.getLogger(__name__)


def _apply_customer_filters(
    where_parts: List[str],
    params: Dict[str, Any],
    db: Session,
) -> None:
    """按配置开关追加客户列表筛选条件（委托给 common/company_filter 统一模块）。"""
    where_parts.extend(build_customer_filter("customer_name", params, use_lifeline=True))


def _apply_company_name_preprocess(
    where_parts: List[str],
    params: Dict[str, Any],
    db: Session,
) -> None:
    """公司名预处理（默认开启）：委托给 common/company_filter 统一模块在 SQL 层施加结构性准入。

    strict_digits=True 与入库前口径保持一致：含阿拉伯数字的名称须为知名数字品牌或
    数字+单位机构名，否则过滤（中文数字品牌如三星/三一不受影响）。
    """
    where_parts.extend(
        build_company_name_preprocess("customer_name", params, strict_digits=True)
    )


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
    # 公司名预处理：去除异常符号 + 合法性准入（默认开启）
    _apply_company_name_preprocess(where_parts, params, db)

    # 合并折叠：已被合并为别名的公司名不单独出现在列表中（持久化合并层，
    # 即使 ETL 重建 DWS 也不会还原，因为映射表独立存在）
    ensure_merge_map_table(db)
    where_parts.append("customer_name NOT IN (SELECT alias_name FROM company_merge_map)")

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

    # 公司名预处理（结果行级）：去除异常符号得到干净显示名，并丢弃清洗后为空/非法的项。
    # SQL 层已做结构性过滤，此处为兜底与显示清洗，正常不会额外丢弃（total 保持准确）。
    cleaned_items: List[Dict[str, Any]] = []
    for it in items:
        raw_name = it.get("customer_name") or ""
        cleaned = clean_company_symbols(raw_name)
        if not cleaned or not is_valid_company_name(cleaned):
            continue
        if cleaned != raw_name:
            it = dict(it)
            it["customer_name"] = cleaned
        cleaned_items.append(it)
    items = cleaned_items

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


def _distinct_column(db: Session, column: str, special_projects: List[str]) -> set:
    """按专项维度取单列去重值，配合 idx_c360_campaign_tag* 索引纯索引扫描，仅返回少量值。

    改为按列 DISTINCT（而非一次性 SELECT 多列后由 Python 去重）后，每条查询命中覆盖索引、
    返回的行数从「整表行数」降为「该列 distinct 值数」，彻底消除 get_filter_options 在 ETL
    高负载窗口因大结果集传输触发的 (2013) 连接失活。
    """
    col_expr = "c.customer_name" if column == "customer_name" else f"c.{column}"
    clauses: List[str] = []
    params: Dict[str, Any] = {}
    # 重客：来自重客快照表，customer_name 优先取重客名称（未进入彩光的重客也可作为候选项）
    if "重客" in special_projects:
        ka_expr = ("COALESCE(ka.`重客名称`, c.customer_name)"
                   if column == "customer_name" else col_expr)
        clauses.append(
            f"SELECT DISTINCT {ka_expr} FROM {KEY_ACCOUNT_TABLE} ka "
            f"LEFT JOIN dws_customer_360 c "
            f"ON c.customer_name = ka.`重客名称` "
            f"AND c.campaign_tag = :ka_src "
            f"WHERE ka.`time` = (SELECT MAX(`time`) FROM {KEY_ACCOUNT_TABLE}) "
            f"AND {ka_expr} IS NOT NULL AND TRIM({ka_expr}) <> ''"
        )
        params["ka_src"] = KEY_ACCOUNT_SOURCE_PROJECT
    # 其余专项：来自 dws_customer_360
    others = [p for p in special_projects if p != "重客"]
    if others:
        clauses.append(
            f"SELECT DISTINCT {col_expr} FROM dws_customer_360 c "
            f"WHERE c.campaign_tag IN :others "
            f"AND {col_expr} IS NOT NULL AND TRIM({col_expr}) <> ''"
        )
        params["others"] = tuple(others)
    # 未选任何专项：返回全部客户
    if not special_projects:
        clauses.append(
            f"SELECT DISTINCT {col_expr} FROM dws_customer_360 c "
            f"WHERE {col_expr} IS NOT NULL AND TRIM({col_expr}) <> ''"
        )
    if not clauses:
        return set()
    sql = text(" UNION ".join(clauses))
    rows = db.execute(sql, params).all()
    return {r[0] for r in rows if r[0] not in (None, "")}


def _filter_option_rows(db: Session, special_projects: List[str]) -> Dict[str, set]:
    """返回所选专项客户群体的维度值集合（结构：{列名: 去重值集合}）。

    逐列调用 _distinct_column，配合 dws_customer_360 上的 campaign_tag 覆盖索引做到纯索引
    扫描，仅返回少量 distinct 值（而非整表行）。
    """
    result: Dict[str, set] = {}
    for column in (*_FILTER_OPTION_COLUMNS, "customer_name"):
        result[column] = _distinct_column(db, column, special_projects)
    return result


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
    """返回与列表同口径的客户群体筛选维度（行业/区域/负责人/名称/阶段/意向/渠道）。

    韧性：若传入会话的连接在长耗时处理/服务端回收后失活（报 2013 Lost connection 或
    PendingRollbackError），回滚并换一个全新会话重试一次，避免一次性网络/连接抖动直接 500。
    """
    special_project = special_project or []

    def _load(sess: Session) -> tuple:
        _rows = _filter_option_rows(sess, special_project)
        _channel_rows = _channel_option_rows(sess, special_project)
        return _rows, _channel_rows

    def _load_with_fold(sess: Session) -> tuple:
        """加载筛选维度，并按合并映射过滤掉已被合并为别名的公司名。"""
        _rows, _channel_rows = _load(sess)
        try:
            _alias_set = {
                r[0]
                for r in sess.execute(
                    text("SELECT alias_name FROM company_merge_map")
                ).all()
            }
        except Exception:
            _alias_set = set()
        # _rows 为 {列名: 去重值集合}，仅剔除已被合并为别名的客户名
        _rows["customer_name"] = {
            _n for _n in _rows["customer_name"] if _n not in _alias_set
        }
        return _rows, _channel_rows

    try:
        rows, channel_rows = _load_with_fold(db)
    except (OperationalError, PendingRollbackError) as _exc:
        logger.warning("get_filter_options 连接失活，尝试换会话重试: %s", _exc)
        try:
            db.rollback()
        except Exception:
            pass
        try:
            db.close()
        except Exception:
            pass
        # 短暂退避，避开瞬时高负载窗口（如 ETL 批量重建 dws_customer_360 时
        # 全表扫描被拖慢导致连接被服务器 net_write_timeout 断开）后再换会话重试
        time.sleep(0.3)
        from app.database import SessionLocal
        with SessionLocal() as _db2:
            rows, channel_rows = _load_with_fold(_db2)

    return {
        "industries": sorted(rows["industry"]),
        "regions": available_region_options(rows["region"]),
        "owners": sorted(rows["owner_name"]),
        "keywords": sorted(rows["customer_name"]),
        "stages": sorted(rows["purchase_stage"]),
        "intent_levels": sorted(rows["intent_level"]),
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
        WHERE customer_name NOT IN (SELECT alias_name FROM company_merge_map)
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
    """返回客户 360 详情，并补充近 30 天互动数与最近拜访信息。

    按合并映射折叠：传入别名 id 时解析到标准公司，并聚合整个合并簇的数据。
    """
    canonical_id, canonical_name, member_ids, member_names = resolve_customer(db, customer_id)
    if canonical_id is None:
        raise CustomerNotFound(customer_id)

    # 合并源公司名：当传入的 customer_id 本身是「被合并的别名」时，
    # 其 dws 原始公司名即为合并前的来源公司名，前端据此标注便于追溯。
    source_row = db.execute(
        text("SELECT customer_name FROM dws_customer_360 WHERE id = :cid"),
        {"cid": customer_id},
    ).mappings().fetchone()
    source_name = source_row["customer_name"] if source_row else None
    merge_source_name = (
        source_name if source_name and source_name != canonical_name else None
    )

    row = db.execute(
        text("SELECT * FROM dws_customer_360 WHERE id = :cid"),
        {"cid": canonical_id},
    ).mappings().fetchone()
    if not row:
        raise CustomerNotFound(customer_id)

    result = dict(row)
    # 合并簇去重计数：联系人按 (contact_name, mobile)，互动按
    # (contact_name, behavior_type, event_time) 去重，避免合并后重复计数。
    contact_count = db.execute(
        text(
            "SELECT COUNT(*) FROM ("
            "  SELECT DISTINCT contact_name, mobile "
            "  FROM dws_contact_360 WHERE customer_id IN :mids"
            ") t"
        ),
        {"mids": tuple(member_ids)},
    ).scalar() or 0
    interaction_count_total = db.execute(
        text(
            "SELECT COUNT(*) FROM ("
            "  SELECT DISTINCT contact_name, behavior_type, event_time "
            "  FROM dws_interaction_detail WHERE customer_name IN :members"
            ") t"
        ),
        {"members": tuple(member_names)},
    ).scalar() or 0
    interaction_count_30d = db.execute(
        text(
            "SELECT COUNT(*) FROM ("
            "  SELECT DISTINCT contact_name, behavior_type, event_time "
            "  FROM dws_interaction_detail "
            "  WHERE customer_name IN :members "
            "    AND event_time >= DATE_SUB(NOW(), INTERVAL 30 DAY)"
            ") t"
        ),
        {"members": tuple(member_names)},
    ).scalar() or 0
    result["contact_count"] = int(contact_count)
    result["interaction_count_total"] = int(interaction_count_total)
    result["interaction_count_30d"] = int(interaction_count_30d)
    # 合并源公司名：非空表示当前数据由该来源公司合并而来，便于追溯原始归属
    result["merge_source_name"] = merge_source_name

    visit_row = db.execute(
        text(
            "SELECT MAX(last_visit_time) AS last_visit_time, "
            "       MIN(not_visit_days) AS no_visit_days "
            "FROM ods_crm_contact_day "
            "WHERE customer_name IN :members"
        ),
        {"members": tuple(member_names)},
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
    canonical_id, canonical_name, member_ids, member_names = resolve_customer(db, customer_id)
    if canonical_id is None or not member_ids:
        raise CustomerNotFound(customer_id)
    customer_row = db.execute(
        text(
            "SELECT customer_name, purchase_stage, intent_level "
            "FROM dws_customer_360 WHERE id = :cid"
        ),
        {"cid": canonical_id},
    ).mappings().fetchone()
    if not customer_row:
        raise CustomerNotFound(customer_id)

    customer_name = canonical_name

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
            "    WHERE customer_name IN :members "
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
            "        WHERE customer_name IN :members "
            "          AND channel IS NOT NULL AND channel != '' "
            "        GROUP BY contact_name, mobile, channel "
            "    ) preferred_ranked "
            "    WHERE rn = 1 "
            ") pc ON pc.contact_name <=> c.contact_name "
            "     AND pc.mobile <=> c.mobile "
            "WHERE c.customer_id IN :member_ids "
            "ORDER BY c.interaction_count DESC, c.contact_name"
        ),
        {
            "member_ids": tuple(member_ids),
            "members": tuple(member_names),
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
                "    WHERE customer_name IN :members "
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
                "        WHERE customer_name IN :members "
                "          AND channel IS NOT NULL AND channel != '' "
                "        GROUP BY contact_name, mobile, channel "
                "    ) preferred_ranked "
                "    WHERE rn = 1 "
                ") pc ON pc.contact_name <=> cm.contact_name "
                "     AND pc.mobile <=> cm.mobile "
                "WHERE cm.customer_name IN :members "
                "ORDER BY cm.contact_name"
            ),
            {
                "members": tuple(member_names),
                "customer_stage": customer_row.get("purchase_stage"),
                "customer_intent_level": customer_row.get("intent_level"),
            },
        ).mappings().all()

    # 按 (contact_name, mobile) 去重：同一人在不同合并公司下合并为一条联系人，
    # 保留互动更丰富的记录（避免合并簇里同一人被重复展示）。
    seen: Dict[tuple, Any] = {}
    for r in rows:
        key = (r.get("contact_name"), r.get("mobile"))
        if key in seen:
            if (r.get("interaction_count") or 0) > (seen[key].get("interaction_count") or 0):
                seen[key] = r
        else:
            seen[key] = r
    contacts = list(seen.values())

    return {
        "customer_id": canonical_id,
        "customer_name": customer_name,
        "contacts": [dict(c) for c in contacts],
        "total": len(contacts),
    }


def get_customer_interactions(
    db: Session,
    customer_id: str,
    limit: int = 50,
) -> Dict[str, Any]:
    """返回客户互动时间线（按 event_time 倒序）。

    按合并映射折叠：聚合整个合并簇的互动。
    """
    canonical_id, canonical_name, member_ids, member_names = resolve_customer(db, customer_id)
    if not member_names:
        raise CustomerNotFound(customer_id)
    members = tuple(member_names)
    # 互动按 (contact_name, behavior_type, event_time) 去重：同一人の同一行为
    # 只算一条互动。LIMIT 作用于去重后的结果，total 反映去重后总数。
    rows = db.execute(
        text(
            "SELECT d.* FROM dws_interaction_detail d "
            "INNER JOIN ("
            "  SELECT MIN(id) AS keep_id FROM dws_interaction_detail "
            "  WHERE customer_name IN :members "
            "  GROUP BY contact_name, behavior_type, event_time"
            ") g ON g.keep_id = d.id "
            "ORDER BY d.event_time DESC "
            "LIMIT :lim"
        ),
        {"members": members, "lim": limit},
    ).mappings().all()
    total = db.execute(
        text(
            "SELECT COUNT(*) FROM ("
            "  SELECT DISTINCT contact_name, behavior_type, event_time "
            "  FROM dws_interaction_detail WHERE customer_name IN :members"
            ") t"
        ),
        {"members": members},
    ).scalar() or 0
    return {
        "customer_id": canonical_id,
        "customer_name": canonical_name,
        "interactions": [dict(r) for r in rows],
        "total": int(total),
    }


def get_customer_opportunities(db: Session, customer_id: str) -> Dict[str, Any]:
    """返回客户 CRM 商机（按 create_date 倒序）。

    按合并映射折叠：聚合整个合并簇的商机。
    """
    canonical_id, canonical_name, member_ids, member_names = resolve_customer(db, customer_id)
    if not member_names:
        raise CustomerNotFound(customer_id)
    rows = db.execute(
        text(
            "SELECT * FROM ods_crm_opportunity_day "
            "WHERE customer_name IN :members "
            "ORDER BY create_date DESC"
        ),
        {"members": tuple(member_names)},
    ).mappings().all()
    return {
        "customer_id": canonical_id,
        "customer_name": canonical_name,
        "opportunities": [dict(r) for r in rows],
        "total": len(rows),
    }


def build_customer_ai_insight(db: Session, customer_id: str) -> Dict[str, Any]:
    """构建客户 AI 洞察（规则结论 + 优先联系人推荐）。

    按合并映射折叠：聚合整个合并簇的数据。
    """
    from app.services.ai.contact_recommend import recommend_priority_contacts

    canonical_id, canonical_name, member_ids, member_names = resolve_customer(db, customer_id)
    if canonical_id is None or not member_names:
        raise CustomerNotFound(customer_id)

    customer_row = db.execute(
        text("SELECT * FROM dws_customer_360 WHERE id = :cid"),
        {"cid": canonical_id},
    ).mappings().fetchone()
    if not customer_row:
        raise CustomerNotFound(customer_id)

    customer = dict(customer_row)

    interaction_count = db.execute(
        text(
            "SELECT COUNT(*) FROM ("
            "  SELECT DISTINCT contact_name, behavior_type, event_time "
            "  FROM dws_interaction_detail "
            "  WHERE customer_name IN :members "
            "    AND event_time >= DATE_SUB(NOW(), INTERVAL 3 MONTH)"
            ") t"
        ),
        {"members": tuple(member_names)},
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
        customer_id=canonical_id,
        customer_name=canonical_name,
        top_n=3,
    )

    return {
        "customer_id": canonical_id,
        "customer_name": canonical_name,
        "business_conclusion": business_conclusion,
        "evidence": evidence,
        "recommendation": priority_result.get("recommendation"),
        "recommendations": priority_result.get("recommendations", []),
        "total_candidates": priority_result.get("total_candidates", 0),
        "source": priority_result.get("source", "rule"),
    }
