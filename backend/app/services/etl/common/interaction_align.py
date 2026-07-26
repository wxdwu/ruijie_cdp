"""将 dws_interaction_detail.customer_name 对齐到 dws_customer_360.customer_name。

背景：互动明细的 customer_name 来自智渠行为 / 天润会话 / linkflow / CRM 线索等多源，
拼写（大小写、全半角、首尾空格）可能与 dws_customer_360 的客户名不一致，导致按客户名
聚合或关联时出现分裂（数据质量报告中的“覆盖缺口 / 别名拆分”）。

本模块在客户360构建完成后，把能与客户360客户名精确匹配（不敏感于大小写、全半角、
首尾空格）的互动行规范化到客户360的标准拼写，从而保证下游按客户名聚合 / 关联一致。

无法匹配的客户（仅出现在互动、但未进入 customer_360 的公司）保持原样，属于正常情况。
"""
import logging

from app.services.etl.common import _exec

logger = logging.getLogger(__name__)


def align_interaction_detail_names(
    customer_360_table: str,
    interaction_detail_table: str,
) -> int:
    """把 interaction_detail 中能与 customer_360 客户名精确匹配的行的 customer_name
    规范化到客户360的标准拼写。

    Args:
        customer_360_table: 客户360表名（全量为主表，增量为 _temp 表）
        interaction_detail_table: 互动明细表名（同上）

    Returns:
        被规范化的互动行数。
    """
    n = _exec(
        f"UPDATE {interaction_detail_table} d "
        f"INNER JOIN {customer_360_table} c "
        "  ON d.customer_name COLLATE utf8mb4_0900_ai_ci "
        "   = c.customer_name COLLATE utf8mb4_0900_ai_ci "
        f"SET d.customer_name = c.customer_name"
    )
    logger.info(
        "对齐互动明细 customer_name：%s <-> %s，规范化 %d 行",
        interaction_detail_table, customer_360_table, n,
    )
    return n
