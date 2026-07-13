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
    region: Optional[str],
    region_keyword: Optional[str],
    prefix: str = "region",
) -> None:
    """Append a region predicate that understands both ``山东`` and ``山东区域``."""
    selected = region or (region_keyword.strip() if region_keyword else None)
    if not selected:
        return

    if selected == "其他":
        placeholders: List[str] = []
        canonical = [option for option in REGION_OPTIONS if option != "其他"]
        for index, value in enumerate(canonical):
            for suffix, stored_value in (("name", value), ("area", f"{value}区域")):
                key = f"{prefix}_standard_{index}_{suffix}"
                placeholders.append(f":{key}")
                params[key] = stored_value
        where_parts.append(
            f"({column} IS NULL OR {column} = '' "
            f"OR {column} NOT IN ({', '.join(placeholders)}))"
        )
        return

    # A dropdown selection is canonical and should include the legacy suffixed value.
    if region:
        exact_key = f"{prefix}_exact"
        area_key = f"{prefix}_area"
        where_parts.append(f"{column} IN (:{exact_key}, :{area_key})")
        params[exact_key] = selected
        params[area_key] = f"{selected}区域"
        return

    keyword_key = f"{prefix}_keyword"
    where_parts.append(f"{column} LIKE :{keyword_key}")
    params[keyword_key] = f"%{selected}%"
