"""合作意向分与等级的单一计算规则。

该规则同时被 ETL 构建（build_dws_customer_360）与客户查询层（合并/撤销后
按簇聚合数据重算）复用，确保「合并后按簇全量数据重算、撤销后按各自实际值
重算」语义一致，且公式只有一处定义。
"""


def compute_intent_score(
    contact_count: int,
    interaction_count_total: int,
    interaction_count_30d: int,
    active_opp_count: int,
) -> int:
    """按统一规则计算合作意向分（封顶 100）。

    公式与 ETL Phase 4 派生字段保持一致：
        意向分 = 近30天互动×2 + (有商机则+20) + (联系人≥3则+10，否则×3)
    """
    contact_count = int(contact_count or 0)
    interaction_count_total = int(interaction_count_total or 0)
    interaction_count_30d = int(interaction_count_30d or 0)
    active_opp_count = int(active_opp_count or 0)

    score = (
        interaction_count_30d * 2
        + (20 if active_opp_count > 0 else 0)
        + (10 if contact_count >= 3 else contact_count * 3)
    )
    return min(100, score)


def compute_intent_level(
    contact_count: int,
    interaction_count_total: int,
    interaction_count_30d: int,
    active_opp_count: int,
) -> str:
    """按统一规则计算合作意向等级。

    规则与 ETL Phase 4 派生字段保持一致：
        高：近30天互动≥10 且 有商机
        中：近30天互动≥3
        低：历史互动>0
        无：其余
    """
    interaction_count_total = int(interaction_count_total or 0)
    interaction_count_30d = int(interaction_count_30d or 0)
    active_opp_count = int(active_opp_count or 0)

    if interaction_count_30d >= 10 and active_opp_count > 0:
        return "高"
    if interaction_count_30d >= 3:
        return "中"
    if interaction_count_total > 0:
        return "低"
    return "无"
