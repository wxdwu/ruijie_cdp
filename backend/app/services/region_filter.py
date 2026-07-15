"""Shared region options and matching rules for customer queries."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


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


def normalize_region(value: Any) -> Optional[str]:
    """Map stored region variants to the canonical filter option."""
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    for option in REGION_OPTIONS:
        if option == "其他":
            continue
        if normalized in (option, f"{option}区域"):
            return option
    return "其他"


def available_region_options(values: Iterable[Any]) -> List[str]:
    """Return only canonical options represented by the supplied rows."""
    present = {normalized for value in values if (normalized := normalize_region(value))}
    return [option for option in REGION_OPTIONS if option in present]


def add_region_filter(
    where_parts: List[str],
    params: Dict[str, Any],
    *,
    column: str,
    region: Optional[Iterable[str]] = None,
    region_keyword: Optional[str] = None,
    prefix: str = "region",
) -> None:
    """Append a region predicate that understands both ``山东`` and ``山东区域``.

    支持多选：``region`` 可以是多个省份构成的序列，最终以 OR 连接。
    """
    regions = [r for r in (region or []) if r]
    if not regions and not region_keyword:
        return

    # 关键词模糊匹配（按结果过滤，独立生效）
    if region_keyword:
        keyword_key = f"{prefix}_keyword"
        where_parts.append(f"{column} LIKE :{keyword_key}")
        params[keyword_key] = f"%{region_keyword.strip()}%"
        if not regions:
            return

    sub_parts: List[str] = []
    for idx, selected in enumerate(regions):
        if selected == "其他":
            canonical = [option for option in REGION_OPTIONS if option != "其他"]
            placeholders: List[str] = []
            for j, value in enumerate(canonical):
                for suffix, stored_value in (("name", value), ("area", f"{value}区域")):
                    key = f"{prefix}_other_{idx}_{j}_{suffix}"
                    placeholders.append(f":{key}")
                    params[key] = stored_value
            sub_parts.append(
                f"({column} IS NULL OR {column} = '' "
                f"OR {column} NOT IN ({', '.join(placeholders)}))"
            )
            continue

        # 下拉选择为规范值，需同时匹配「广东」与历史「广东区域」写法
        exact_key = f"{prefix}_exact_{idx}"
        area_key = f"{prefix}_area_{idx}"
        sub_parts.append(f"{column} IN (:{exact_key}, :{area_key})")
        params[exact_key] = selected
        params[area_key] = f"{selected}区域"

    if sub_parts:
        where_parts.append("(" + " OR ".join(sub_parts) + ")")
