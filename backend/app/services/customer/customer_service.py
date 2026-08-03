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
from app.services.common.intent import (
    compute_intent_level,
    compute_intent_score,
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


def _enrich_list_intent_scores(db: Session, items: List[Dict[str, Any]]) -> None:
    """对合并簇内的 canonical 公司，用簇级聚合数据重算合作意向分。

    取 max(簇计算值, dws 当前字段值)，确保 /customers 列表页与
    /customers/{id} 详情页展示的意向分和意向等级数值一致。
    """
    if not items:
        return

    # 收集当前页所有公司名
    names = [item["customer_name"] for item in items if item.get("customer_name")]
    if not names:
        return

    # 找出哪些公司是 canonical（有合并别名）
    merge_rows = db.execute(
        text(
            "SELECT canonical_name, alias_name FROM company_merge_map "
            "WHERE canonical_name IN :names"
        ),
        {"names": tuple(names)},
    ).mappings().all()

    if not merge_rows:
        return

    # 构建 canonical → 所有成员名（含自身别名）
    canonical_members: dict = {}
    for row in merge_rows:
        cn = row["canonical_name"]
        an = row["alias_name"]
        if cn not in canonical_members:
            canonical_members[cn] = {cn}
        canonical_members[cn].add(an)

    # 对每个 canonical 按簇聚合数据重算意向分
    for item in items:
        cn = item.get("customer_name")
        if cn not in canonical_members:
            continue
        members = tuple(canonical_members[cn])

        # 联系人（簇内去重）
        cluster_contact = db.execute(
            text(
                "SELECT COUNT(*) FROM ("
                "  SELECT DISTINCT contact_name, mobile "
                "  FROM dws_contact_mapping "
                "  WHERE customer_name IN :members"
                ") t"
            ),
            {"members": members},
        ).scalar() or 0

        # 互动总数（簇内去重）
        cluster_interaction_total = db.execute(
            text(
                "SELECT COUNT(*) FROM ("
                "  SELECT DISTINCT contact_name, behavior_type, event_time "
                "  FROM dws_interaction_detail "
                "  WHERE customer_name IN :members"
                ") t"
            ),
            {"members": members},
        ).scalar() or 0

        # 近30天互动（簇内去重）
        cluster_interaction_30d = db.execute(
            text(
                "SELECT COUNT(*) FROM ("
                "  SELECT DISTINCT contact_name, behavior_type, event_time "
                "  FROM dws_interaction_detail "
                "  WHERE customer_name IN :members "
                "    AND event_time >= DATE_SUB(NOW(), INTERVAL 30 DAY)"
                ") t"
            ),
            {"members": members},
        ).scalar() or 0

        # 商机数（簇内求和）
        opp_row = db.execute(
            text(
                "SELECT COALESCE(SUM(active_opp_count), 0) AS s "
                "FROM dws_customer_360 WHERE customer_name IN :members"
            ),
            {"members": members},
        ).fetchone()
        cluster_active_opp = int(opp_row[0]) if opp_row and opp_row[0] else 0

        cluster_intent = compute_intent_score(
            contact_count=cluster_contact,
            interaction_count_total=cluster_interaction_total,
            interaction_count_30d=cluster_interaction_30d,
            active_opp_count=cluster_active_opp,
        )
        cluster_level = compute_intent_level(
            contact_count=cluster_contact,
            interaction_count_total=cluster_interaction_total,
            interaction_count_30d=cluster_interaction_30d,
            active_opp_count=cluster_active_opp,
        )

        # 取 max(簇计算值，dws 当前字段值)
        current_intent = item.get("intent_score") or 0
        item["intent_score"] = max(cluster_intent, current_intent)
        item["intent_level"] = cluster_level


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

    # 对合并簇内的 canonical 公司，用簇级聚合数据重算意向分，
    # 取 max(簇计算值, dws 当前值)，确保列表页与详情页数值一致。
    _enrich_list_intent_scores(db, items)

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

_FILTER_OPTION_DIMENSIONS = {
    "industry": "industry",
    "region": "region",
    "owner": "owner_name",
    "stage": "purchase_stage",
    "intent_level": "intent_level",
}


def _facet_selects(from_sql: str, base_where: str) -> List[str]:
    """Build bounded GROUP BY selects so MySQL, not Python, performs deduplication."""
    selects: List[str] = []
    for option_type, column in _FILTER_OPTION_DIMENSIONS.items():
        selects.append(
            f"SELECT '{option_type}' AS option_type, c.{column} AS option_value "
            f"{from_sql} WHERE {base_where} "
            f"AND c.{column} IS NOT NULL AND TRIM(c.{column}) != '' "
            f"GROUP BY c.{column}"
        )
    return selects


def _filter_option_rows(db: Session, special_projects: List[str]) -> List[Any]:
    """Return only distinct low-cardinality facets for the selected populations."""
    selects: List[str] = []
    params: Dict[str, Any] = {}

    if "重客" in special_projects:
        selects.extend(_facet_selects(
            f"FROM {KEY_ACCOUNT_TABLE} ka "
            "LEFT JOIN dws_customer_360 c "
            "ON c.customer_name = ka.`重客名称` "
            "AND c.campaign_tag = :filter_source_project",
            f"ka.`time` = (SELECT MAX(`time`) FROM {KEY_ACCOUNT_TABLE})",
        ))
        params["filter_source_project"] = KEY_ACCOUNT_SOURCE_PROJECT

    others = [project for project in special_projects if project != "重客"]
    if others:
        selects.extend(_facet_selects(
            "FROM dws_customer_360 c",
            "c.campaign_tag IN :filter_other_projects",
        ))
        params["filter_other_projects"] = tuple(others)

    if not special_projects:
        selects.extend(_facet_selects("FROM dws_customer_360 c", "1=1"))

    if not selects:
        return []
    return db.execute(text(" UNION ALL ".join(selects)), params).mappings().all()


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
            SELECT channel_candidate.channel
            FROM (
                SELECT channel
                FROM dws_interaction_detail
                WHERE channel IS NOT NULL AND TRIM(channel) != ''
                GROUP BY channel
            ) channel_candidate
            WHERE EXISTS (
                SELECT 1
                FROM dws_interaction_detail interaction FORCE INDEX (idx_channel)
                INNER JOIN dws_customer_360 c
                  ON c.customer_name = interaction.customer_name
                WHERE interaction.channel = channel_candidate.channel
                  AND c.campaign_tag IN :channel_other_projects
            )
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
    """返回低基数筛选维度；客户名称由远程建议接口按需检索。

    韧性：若传入会话的连接在长耗时处理/服务端回收后失活（报 2013 Lost connection 或
    PendingRollbackError），回滚并换一个全新会话重试一次，避免一次性网络/连接抖动直接 500。
    """
    special_project = special_project or []

    def _load(sess: Session) -> tuple:
        _rows = _filter_option_rows(sess, special_project)
        _channel_rows = _channel_option_rows(sess, special_project)
        return _rows, _channel_rows

    try:
        rows, channel_rows = _load(db)
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
            rows, channel_rows = _load(_db2)

    options: Dict[str, List[str]] = {key: [] for key in _FILTER_OPTION_DIMENSIONS}
    for row in rows:
        option_type = row.get("option_type")
        option_value = row.get("option_value")
        if option_type not in options or option_value in (None, ""):
            continue
        options[option_type].append(str(option_value).strip())
    return {
        "industries": sorted(set(options["industry"])),
        "regions": available_region_options(options["region"]),
        "owners": sorted(set(options["owner"])),
        # 兼容旧响应；完整名称目录由 name-options 分页读取，不再塞进筛选响应。
        "keywords": [],
        "stages": sorted(set(options["stage"])),
        "intent_levels": sorted(set(options["intent_level"])),
        "channels": available_channel_options(row.get("channel") for row in channel_rows),
    }


def _escape_like_prefix(value: str) -> str:
    """Escape MySQL LIKE wildcards using '=' as the explicit escape character."""
    return value.replace("=", "==").replace("%", "=%").replace("_", "=_") + "%"


def _load_merged_aliases(db: Session) -> tuple[str, ...]:
    """Best-effort load of company aliases that must stay folded into canonical names."""
    try:
        rows = db.execute(text("SELECT alias_name FROM company_merge_map")).all()
    except Exception as exc:
        logger.warning("读取公司合并别名失败，名称选项暂不折叠: %s", exc)
        return ()
    return tuple(sorted({
        str(row[0]).strip()
        for row in rows
        if row[0] not in (None, "") and str(row[0]).strip()
    }))


def _load_customer_names(
    db: Session,
    *,
    special_project: Optional[List[str]] = None,
    query: Optional[str] = None,
    fetch_limit: Optional[int] = None,
) -> List[str]:
    """Load de-duplicated names from the standard and key-account sources."""
    special_projects = special_project or []
    normalized_query = (query or "").strip()
    prefix = _escape_like_prefix(normalized_query) if normalized_query else None
    merged_aliases = _load_merged_aliases(db)
    names: set[str] = set()

    if "重客" in special_projects:
        key_account_filters = [
            f"ka.`time` = (SELECT MAX(`time`) FROM {KEY_ACCOUNT_TABLE})",
            "ka.`重客名称` IS NOT NULL",
            "TRIM(ka.`重客名称`) != ''",
        ]
        key_account_params: Dict[str, Any] = {}
        if merged_aliases:
            key_account_filters.append("ka.`重客名称` NOT IN :merged_aliases")
            key_account_params["merged_aliases"] = merged_aliases
        if prefix is not None:
            key_account_filters.append("ka.`重客名称` LIKE :suggest_prefix ESCAPE '='")
            key_account_params["suggest_prefix"] = prefix
        limit_clause = ""
        if fetch_limit is not None:
            limit_clause = " LIMIT :suggest_limit"
            key_account_params["suggest_limit"] = fetch_limit
        key_account_rows = db.execute(
            text(
                f"SELECT DISTINCT ka.`重客名称` AS customer_name "
                f"FROM {KEY_ACCOUNT_TABLE} ka "
                f"WHERE {' AND '.join(key_account_filters)} "
                f"ORDER BY customer_name{limit_clause}"
            ),
            key_account_params,
        ).mappings().all()
        names.update(
            str(row.get("customer_name")).strip()
            for row in key_account_rows
            if row.get("customer_name") not in (None, "")
        )

    others = [project for project in special_projects if project != "重客"]
    if others or not special_projects:
        where_parts = [
            "c.customer_name IS NOT NULL",
            "TRIM(c.customer_name) != ''",
        ]
        params: Dict[str, Any] = {}
        if merged_aliases:
            where_parts.append("c.customer_name NOT IN :merged_aliases")
            params["merged_aliases"] = merged_aliases
        if prefix is not None:
            where_parts.append("c.customer_name LIKE :suggest_prefix ESCAPE '='")
            params["suggest_prefix"] = prefix
        if others:
            where_parts.append("c.campaign_tag IN :suggest_projects")
            params["suggest_projects"] = tuple(others)
        limit_clause = ""
        if fetch_limit is not None:
            limit_clause = " LIMIT :suggest_limit"
            params["suggest_limit"] = fetch_limit
        standard_rows = db.execute(
            text(
                "SELECT DISTINCT c.customer_name AS customer_name "
                "FROM dws_customer_360 c "
                f"WHERE {' AND '.join(where_parts)} "
                f"ORDER BY c.customer_name{limit_clause}"
            ),
            params,
        ).mappings().all()
        names.update(
            str(row.get("customer_name")).strip()
            for row in standard_rows
            if row.get("customer_name") not in (None, "")
        )

    names.difference_update(merged_aliases)
    return sorted(names)


def get_all_customer_names(
    db: Session,
    *,
    special_project: Optional[List[str]] = None,
) -> List[str]:
    """Load the complete name catalog used to build the Redis sorted set."""
    return _load_customer_names(db, special_project=special_project)


def get_customer_name_options(
    db: Session,
    *,
    query: Optional[str] = None,
    special_project: Optional[List[str]] = None,
    offset: int = 0,
    limit: int = 50,
) -> Dict[str, Any]:
    """Return one browsable/searchable page when the Redis catalog is unavailable."""
    special_projects = special_project or []
    normalized_query = (query or "").strip()
    prefix = _escape_like_prefix(normalized_query) if normalized_query else None
    merged_aliases = _load_merged_aliases(db)
    selects: List[str] = []
    params: Dict[str, Any] = {
        "option_limit": limit + 1,
        "option_offset": offset,
    }

    if "重客" in special_projects:
        key_account_filters = [
            f"ka.`time` = (SELECT MAX(`time`) FROM {KEY_ACCOUNT_TABLE})",
            "ka.`重客名称` IS NOT NULL",
            "TRIM(ka.`重客名称`) != ''",
        ]
        if merged_aliases:
            key_account_filters.append("ka.`重客名称` NOT IN :merged_aliases")
            params["merged_aliases"] = merged_aliases
        if prefix is not None:
            key_account_filters.append("ka.`重客名称` LIKE :option_prefix ESCAPE '='")
            params["option_prefix"] = prefix
        selects.append(
            f"SELECT DISTINCT ka.`重客名称` AS customer_name "
            f"FROM {KEY_ACCOUNT_TABLE} ka "
            f"WHERE {' AND '.join(key_account_filters)}"
        )

    others = [project for project in special_projects if project != "重客"]
    if others or not special_projects:
        standard_filters = [
            "c.customer_name IS NOT NULL",
            "TRIM(c.customer_name) != ''",
        ]
        if merged_aliases:
            standard_filters.append("c.customer_name NOT IN :merged_aliases")
            params["merged_aliases"] = merged_aliases
        if prefix is not None:
            standard_filters.append("c.customer_name LIKE :option_prefix ESCAPE '='")
            params["option_prefix"] = prefix
        if others:
            standard_filters.append("c.campaign_tag IN :option_projects")
            params["option_projects"] = tuple(others)
        selects.append(
            "SELECT DISTINCT c.customer_name AS customer_name "
            "FROM dws_customer_360 c "
            f"WHERE {' AND '.join(standard_filters)}"
        )

    rows = db.execute(
        text(
            "SELECT customer_name FROM ("
            + " UNION ".join(selects)
            + ") customer_name_options "
            "ORDER BY customer_name "
            "LIMIT :option_limit OFFSET :option_offset"
        ),
        params,
    ).mappings().all()
    names = [
        str(row.get("customer_name")).strip()
        for row in rows
        if (
            row.get("customer_name") not in (None, "")
            and str(row.get("customer_name")).strip() not in merged_aliases
        )
    ]
    return {
        "items": names[:limit],
        "has_more": len(names) > limit,
    }


def get_customer_name_suggestions(
    db: Session,
    *,
    query: str,
    special_project: Optional[List[str]] = None,
    limit: int = 30,
) -> Dict[str, Any]:
    """Return bounded, prefix-matched customer names for the remote multi-select."""
    ordered = _load_customer_names(
        db,
        query=query,
        special_project=special_project,
        fetch_limit=limit + 1,
    )
    return {
        "items": ordered[:limit],
        "has_more": len(ordered) > limit,
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

    # 合并簇内商机数也需按簇聚合（各成员公司 active_opp_count 求和），
    # 否则合并后意向分仍只取 canonical 原值，无法体现别名公司的在途商机。
    opp_row = db.execute(
        text(
            "SELECT COALESCE(SUM(active_opp_count), 0) AS active_opp_count "
            "FROM dws_customer_360 WHERE customer_name IN :members"
        ),
        {"members": tuple(member_names)},
    ).mappings().fetchone()
    cluster_active_opp = int(opp_row["active_opp_count"]) if opp_row else 0

    # 合并/撤销后，按当前簇聚合出来的「联系人数 + 互动记录 + 商机数」重新计算
    # 合作意向分与等级（规则见 app.services.common.intent，与 ETL 派生字段一致）。
    # 合并时簇包含所有成员公司→全量数据重算；撤销时别名恢复独立、仅自身数据→重算。
    # 取 max(簇计算值, dws 原始字段值)，确保合并后不会意外低估。
    original_intent = result.get("intent_score") or 0
    result["active_opp_count"] = cluster_active_opp
    result["intent_score"] = max(
        compute_intent_score(
            contact_count=result["contact_count"],
            interaction_count_total=result["interaction_count_total"],
            interaction_count_30d=result["interaction_count_30d"],
            active_opp_count=cluster_active_opp,
        ),
        original_intent,
    )
    result["intent_level"] = compute_intent_level(
        contact_count=result["contact_count"],
        interaction_count_total=result["interaction_count_total"],
        interaction_count_30d=result["interaction_count_30d"],
        active_opp_count=cluster_active_opp,
    )
    # 合并源公司名：非空表示当前数据由该来源公司合并而来，便于追溯原始归属
    result["merge_source_name"] = merge_source_name

    # 合并链追溯信息：最终合并者展示「合并了几家 + hover 看具体成员」；
    # 被合并者展示「从当前到最终合并者的逐步合并链」，带环检测与超长折叠。
    from app.services.company_dedup.company_merge import get_merge_chain
    result["merge_chain_info"] = get_merge_chain(db, customer_id)

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
