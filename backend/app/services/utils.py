"""跨 services 共享的通用工具函数。

集中放置被多个 service 重复实现的小工具（JSON 解析、Decimal/datetime → JSON 安全、
IN 多选占位符拼接等），避免相同逻辑散落多份、行为不一致。
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, List, MutableMapping, Optional, Sequence


def to_json_safe(value: Any) -> Any:
    """将单值转换为 JSON 可序列化类型。

    处理 MySQL/SQLAlchemy 返回的常见特殊类型：
    - Decimal → float
    - datetime / date → ISO 字符串
    - 其余原样返回。
    """
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def row_to_json_safe(row: dict) -> dict:
    """将一整行（dict）转换为 JSON 可序列化 dict，就地返回新 dict。"""
    return {key: to_json_safe(value) for key, value in row.items()}


def safe_json_loads(value: Any, default: Any = None) -> Any:
    """安全解析可能是 JSON 字符串的列值。

    传入已是 dict/list 的（如 SQLAlchemy 的 JSON 列）直接返回；
    传入字符串则尝试 json.loads，解析失败或为空返回 default。
    """
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        text_value = value.strip()
        if not text_value or text_value in {"null", "[]", "{}"}:
            return default
        try:
            return json.loads(text_value)
        except (json.JSONDecodeError, TypeError):
            return default
    return default


def add_in_filter(
    where_parts: List[str],
    params: MutableMapping[str, Any],
    column: str,
    values: Optional[Sequence[str]],
    prefix: str,
) -> None:
    """向 WHERE 子句追加 ``column IN (:p0, :p1, ...)`` 谓词，支持多选维度过滤。

    抽取自 customer_service / key_account_query 中重复的同名函数，统一为共享实现。
    """
    if not values:
        return
    placeholders: List[str] = []
    for index, value in enumerate(values):
        key = f"{prefix}_{index}"
        params[key] = value
        placeholders.append(f":{key}")
    where_parts.append(f"{column} IN ({', '.join(placeholders)})")
