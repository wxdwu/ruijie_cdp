"""公司名过滤（白/黑名单 + 名称预处理）统一模块。

把原本散落在 customer_service 的客户列表筛选条件，封装为可复用的纯函数，
既服务客户列表查询，也供 ETL 全量/增量聚合（构建 dws_customer_360 等）在 SQL 层复用同一套规则。

底层依赖（仍为单一来源，本模块仅做编排与 SQL 片段构建）：
- common/company_name_clean（干净化 / 合法判定）
- common/company_whitelist（白名单正则）
- common/company_blacklist（黑名单正则）
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.config import settings
from app.services.common.company_name_clean import (
    clean_company_symbols,
    is_valid_company_name,
)
from app.services.common.company_whitelist import (
    VALID_COMPANY_REGEX,
    VALID_WHITELIST_PATTERNS,
    KNOWN_DIGIT_BRAND_PATTERN,
    DIGIT_UNIT_PATTERN,
)
from app.services.common.company_blacklist import VALID_BLACKLIST_PATTERNS

logger = logging.getLogger(__name__)


def build_customer_filter(
    column: str,
    params: Dict[str, Any],
    *,
    use_lifeline: bool = True,
) -> List[str]:
    """追加客户列表筛选条件片段，返回 SQL 片段列表（供调用方用 AND/OR 拼接进 WHERE）。

    column: 公司名字段名（如 customer_name / 关联公司 / key_customer_name）。
    use_lifeline: 是否加入“保命条件”（有联系人/互动的行始终保留）。
        仅当该表含 contact_count / interaction_count_total 等列时（dws_customer_360）才为 True；
        ETL 聚合中间表无这些列，应传 False，表示仅按正则过滤、不套保命条件。

    规则（均受“保命条件”保护：有联系人/互动的行始终保留，避免误删有效数据）：
    - 非法公司名/用户名：customer_name 不含任何企业特征词且无联系人与互动的行被剔除。
    - 黑名单（精确）：命中的公司名被剔除（当前默认禁用）。
    - 白名单（允许名单）：仅白名单内公司名保留（当前默认禁用）。
    """
    if not settings.CUSTOMER_FILTER_ENABLED:
        return []

    # 内置默认规则（白/黑名单以 Python 常量提供，无需写入数据库）
    whitelist = list(VALID_WHITELIST_PATTERNS)
    blacklist = list(VALID_BLACKLIST_PATTERNS)

    if not whitelist and not blacklist and not settings.CUSTOMER_FILTER_ILLEGAL_ENABLED:
        return []

    sub: List[str] = []
    # 保命条件：有联系人或有互动的行始终保留
    if use_lifeline:
        sub.append("(contact_count > 0 OR interaction_count_total > 0)")
    # 命中白名单任意规则 → 保留
    if whitelist:
        sub.append(f"{column} REGEXP :filter_wl")
        params["filter_wl"] = "|".join(whitelist)
    # 未命中黑名单任意规则 → 保留（即：命中黑名单且无数据才剔除）
    if blacklist:
        sub.append(f"{column} NOT REGEXP :filter_bl")
        params["filter_bl"] = "|".join(blacklist)
    # 非法公司名规则（可选）：不含企业特征词且无数据则剔除
    if settings.CUSTOMER_FILTER_ILLEGAL_ENABLED:
        sub.append(f"({column} REGEXP :valid_company_regex OR (contact_count > 0 OR interaction_count_total > 0))")
        params.setdefault("valid_company_regex", VALID_COMPANY_REGEX)

    return ["(" + " OR ".join(sub) + ")"]


def build_company_name_preprocess(
    column: str,
    params: Dict[str, Any],
    *,
    strict_digits: bool = False,
) -> List[str]:
    """公司名预处理（默认开启）：在 SQL 层施加结构性合法准入，返回 SQL 片段列表。

    在 SQL 层施加结构性过滤（保持分页总数准确），清洗与最终校验在结果行上再做一次。
    规则对应：
    （2）括号成对：左括号存在则右括号必须存在，反之亦然（半角/全角分别判断）；
    （3）数字连续不超过 4：5 位及以上（手机号/ID 片段）直接剔除；
    （5）像公司而非口语：含企业特征词 / 纯英文数字 / 命中知名品牌 /
        含数字（strict_digits=False 时任意含数字即放行；strict_digits=True 时收紧，见下）。

    strict_digits:
        - False（默认，客户列表展示口径）：含数字即视为像公司（历史宽松行为）。
        - True（全量/增量同步入库前口径）：名称含阿拉伯数字时，必须是
          「知名数字品牌」或「数字+单位机构名」，否则按非法过滤。
          中文数字品牌（三星/三一等）按普通字符处理，不触发该门槛。
    """
    if not settings.CUSTOMER_NAME_CLEAN_ENABLED:
        return []

    conds: List[str] = []

    # （3）连续数字不超过 4
    conds.append(f"{column} NOT REGEXP '[0-9]{{5,}}'")

    # （2）括号成对：半角与全角分别判断，存在一侧则另一侧必须存在
    has_left = f"{column} REGEXP '[（(]'"
    has_right = f"{column} REGEXP '[）)]'"
    conds.append(
        f"((NOT ({has_left} AND NOT {has_right})) "
        f"AND (NOT ({has_right} AND NOT {has_left})))"
    )

    # （5）像公司：含特征词 / 纯英文数字 / 品牌 / 含数字
    # 纯英文判定要求至少含一个字母或数字，避免「.,&」等纯标点被误判为英文公司。
    # 通用参数（两种模式都可能用到）
    params["cn_clean_feature"] = VALID_COMPANY_REGEX
    params["cn_clean_brand"] = VALID_WHITELIST_PATTERNS[1]  # ^(腾讯|...|长安)$
    if strict_digits:
        # 数字规则收紧：含阿拉伯数字的名称，必须是知名数字品牌或数字+单位机构名，
        # 否则视为非法。中文数字（三星/三一等）按普通字符，走特征词/品牌判定。
        params["cn_clean_digit_unit"] = DIGIT_UNIT_PATTERN
        params["cn_clean_digit_brand"] = KNOWN_DIGIT_BRAND_PATTERN
        signal = (
            f"({column} REGEXP :cn_clean_digit_unit "        # 数字+单位机构名
            f"OR {column} REGEXP :cn_clean_digit_brand "     # 知名数字品牌
            f"OR ({column} NOT REGEXP '[0-9]' AND ("         # 无阿拉伯数字：原规则
            f"{column} REGEXP :cn_clean_feature "
            f"OR {column} REGEXP '^[A-Za-z0-9 .&-]*[A-Za-z0-9][A-Za-z0-9 .&-]*$' "
            f"OR {column} REGEXP :cn_clean_brand)))"
        )
    else:
        signal = (
            f"({column} REGEXP :cn_clean_feature "
            f"OR {column} REGEXP '^[A-Za-z0-9 .&-]*[A-Za-z0-9][A-Za-z0-9 .&-]*$' "
            f"OR {column} REGEXP :cn_clean_brand "
            f"OR {column} REGEXP '[0-9]')"
        )
    conds.append(signal)

    return ["(" + " AND ".join(conds) + ")"]


def build_customer_list_filter(
    column: str,
    params: Dict[str, Any],
    *,
    use_lifeline: bool = True,
    strict_digits: bool = False,
) -> List[str]:
    """组合公司名预处理 + 白黑名单过滤，返回可直接追加到 WHERE 的 SQL 片段列表。

    默认 use_lifeline=True（按 dws_customer_360 语义）；ETL 聚合中间表无 contact_count
    等列，请传 use_lifeline=False。strict_digits 透传给 build_company_name_preprocess，
    全量/增量同步入库前调用方应传 True 以收紧数字规则。
    """
    fragments: List[str] = []
    fragments.extend(
        build_company_name_preprocess(column, params, strict_digits=strict_digits)
    )
    fragments.extend(build_customer_filter(column, params, use_lifeline=use_lifeline))
    return fragments
