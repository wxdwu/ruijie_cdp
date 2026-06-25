"""Shared region options for customer queries."""
from __future__ import annotations

from typing import List


REGION_OPTIONS = [
    "广东",
    "天津",
    "黑吉",
    "山东",
    "浙江",
    "上海",
    "湖南",
    "河南",
    "安徽",
    "福建",
    "湖北",
    "广西",
    "辽宁",
    "深圳",
    "甘青宁",
    "北京",
    "贵州",
    "川藏",
    "蒙晋",
    "陕西",
    "河北",
    "江苏",
    "云南",
    "江西",
    "重庆",
    "新疆",
    "其他",
]

def get_region_options() -> List[str]:
    """Return display options in business-defined order."""
    return REGION_OPTIONS.copy()
