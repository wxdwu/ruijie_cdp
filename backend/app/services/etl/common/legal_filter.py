"""DWS 聚合完成后,按 company_filter 规则清理不合法公司名行。

供 full_sync / incremental_sync 在各自 build_dws_* 聚合写入之后调用,
使写入 dws_customer_360 / dws_contact_mapping / dws_interaction_detail 的
公司名都满足与前端客户列表一致的"合法公司名"口径(像公司名 + 白/黑名单 +
保命条件),避免脏数据进入 DWS。

dws_contact_360 无公司名列,由已清理的 dws_customer_360 通过 customer_id
间接收敛,无需单独清理。
"""
from __future__ import annotations

import logging

from app.services.etl.common.db import _exec
from app.services.common.company_filter import build_customer_list_filter

logger = logging.getLogger(__name__)


def clean_dws_table_by_company_filter(
    table: str, column: str, *, use_lifeline: bool = True
) -> int:
    """聚合写入完成后,按 company_filter 的"合法公司名"规则清理 DWS 表。

    删除不满足 (像公司名 AND (保命 OR 命中白名单 OR 未命中黑名单)) 的行。

    table / column 为内部常量(非用户输入),直接拼接到 SQL 是安全的。
    若当前开关下未启用任何规则(build_customer_list_filter 返回空条件),
    则不删除任何行,直接返回 0。

    use_lifeline:
        - True: 适用于含 contact_count / interaction_count_total 列的表
          (dws_customer_360),启用保命条件(有联系人或互动则保留);
        - False: 适用于无上述列的表(dws_contact_mapping / dws_interaction_detail)。
    """
    params: dict = {}
    # strict_digits=True：入库前收紧数字规则（含阿拉伯数字的名称须为知名数字品牌
    # 或数字+单位机构名，否则过滤），与前端客户列表口径保持一致并防止脏数据进入 DWS。
    conds = build_customer_list_filter(
        column, params, use_lifeline=use_lifeline, strict_digits=True
    )
    if not conds:
        logger.info("company_filter 未启用,跳过 %s.%s 合法化清理", table, column)
        return 0
    where = " AND ".join(conds)
    # build_customer_filter 默认用 c360 别名引用保命列,故 use_lifeline=True 时
    # DELETE 需带同名表别名才能解析 contact_count / interaction_count_total。
    if use_lifeline:
        sql = f"DELETE c360 FROM {table} c360 WHERE NOT ({where})"
    else:
        sql = f"DELETE FROM {table} WHERE NOT ({where})"
    removed = _exec(sql, params)
    logger.info(
        "按 company_filter 规则清理 %s.%s: 删除 %d 行不合法公司名",
        table, column, removed,
    )
    return removed
