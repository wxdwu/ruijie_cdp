"""合作意向分/等级计算规则的单元测试。

确保合并/撤销后按「联系人数 + 互动记录 + 商机数」重算的规则只有一处定义，
且与 ETL 派生字段公式保持一致。
"""
import pytest

from app.services.common.intent import (
    compute_intent_level,
    compute_intent_score,
)


def test_score_formula_matches_etl():
    # 近30天互动×2 + 有商机+20 + (联系人≥3则+10, 否则×3)，封顶100
    assert compute_intent_score(contact_count=7, interaction_count_total=3,
                                interaction_count_30d=0, active_opp_count=0) == 10  # 7*3=21? 7>=3→10
    # 联系人≥3 取固定 +10
    assert compute_intent_score(contact_count=7, interaction_count_total=3,
                                interaction_count_30d=0, active_opp_count=0) == 10
    # 联系人<3 按 ×3
    assert compute_intent_score(contact_count=2, interaction_count_total=1,
                                interaction_count_30d=0, active_opp_count=0) == 6
    # 近30天互动+商机
    assert compute_intent_score(contact_count=3, interaction_count_total=5,
                                interaction_count_30d=10, active_opp_count=1) == 50  # 20+20+10
    # 封顶 100
    assert compute_intent_score(contact_count=10, interaction_count_total=100,
                                interaction_count_30d=60, active_opp_count=5) == 100


def test_level_rule():
    # 高：近30天≥10 且 有商机
    assert compute_intent_level(3, 5, 10, 1) == "高"
    # 中：近30天≥3（即使无商机）
    assert compute_intent_level(3, 5, 3, 0) == "中"
    # 低：仅历史互动>0
    assert compute_intent_level(1, 1, 0, 0) == "低"
    # 无：全空
    assert compute_intent_level(0, 0, 0, 0) == "无"
    # 近30天<3 但无历史互动 → 无
    assert compute_intent_level(0, 0, 1, 0) == "无"


def test_merged_cluster_aggregates():
    # 合并后：簇聚合联系人数(7) + 历史互动(3)，无商机 → 分数=10 等级=低
    score = compute_intent_score(7, 3, 0, 0)
    level = compute_intent_level(7, 3, 0, 0)
    assert score == 10 and level == "低"


def test_revoked_uses_own_values():
    # 撤销后：别名自身无数据 → 0/无；若自身有数据则按自身重算
    assert compute_intent_score(0, 0, 0, 0) == 0
    assert compute_intent_level(0, 0, 0, 0) == "无"
