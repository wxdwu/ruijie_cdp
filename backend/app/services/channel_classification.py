"""Temporary normalization for customer interaction-channel values.

The customer 360 table currently contains both canonical channel codes and
source-system values.  Keep the UI contract stable until the upstream field is
normalized by grouping every non-empty, non-canonical value into ``other``.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, MutableMapping, Sequence


CHANNEL_ALIASES: Dict[str, Sequence[str]] = {
    "email": ("email", "邮件"),
    "web": ("web", "官网"),
    "event": ("event", "直播/活动"),
    "wechat": ("wechat", "微信"),
}

OTHER_CHANNEL = "other"
UNREACHED_CHANNEL = "无渠道/未触达"
CHANNEL_FILTER_ORDER = (*CHANNEL_ALIASES.keys(), OTHER_CHANNEL)


def normalize_channel(value: Any) -> str:
    """Normalize one raw customer channel to the dashboard category."""
    if value is None or not str(value).strip():
        return UNREACHED_CHANNEL

    normalized = str(value).strip()
    for canonical, aliases in CHANNEL_ALIASES.items():
        if normalized in aliases:
            return canonical
    return OTHER_CHANNEL


def available_channel_options(values: Iterable[Any]) -> List[str]:
    """Return canonical UI channels that occur in the supplied interaction rows."""
    present = {
        normalized
        for value in values
        if (normalized := normalize_channel(value)) != UNREACHED_CHANNEL
    }
    return [channel for channel in CHANNEL_FILTER_ORDER if channel in present]


def _bind_values(
    params: MutableMapping[str, Any],
    values: Sequence[str],
    *,
    prefix: str,
) -> str:
    placeholders: List[str] = []
    for index, value in enumerate(values):
        key = f"{prefix}_{index}"
        params[key] = value
        placeholders.append(f":{key}")
    return ", ".join(placeholders)


def add_channel_filter(
    where_parts: List[str],
    params: MutableMapping[str, Any],
    *,
    column: str,
    channel: str | None,
    prefix: str = "channel_value",
) -> None:
    """Append a canonical/other channel filter to an existing WHERE clause."""
    if not channel:
        return

    if channel == OTHER_CHANNEL:
        known_values = tuple(
            value
            for aliases in CHANNEL_ALIASES.values()
            for value in aliases
        )
        placeholders = _bind_values(params, known_values, prefix=prefix)
        where_parts.append(
            f"({column} IS NOT NULL AND TRIM({column}) != '' "
            f"AND {column} NOT IN ({placeholders}))"
        )
        return

    aliases = CHANNEL_ALIASES.get(channel, (channel,))
    placeholders = _bind_values(params, aliases, prefix=prefix)
    where_parts.append(f"{column} IN ({placeholders})")


def add_customer_interaction_channel_filter(
    where_parts: List[str],
    params: MutableMapping[str, Any],
    *,
    customer_name_column: str,
    channel: str | None,
    prefix: str = "interaction_channel",
) -> None:
    """Filter customers by any matching interaction-detail channel."""
    if not channel:
        return
    channel_parts: List[str] = []
    add_channel_filter(
        channel_parts,
        params,
        column="interaction_channel.channel",
        channel=channel,
        prefix=prefix,
    )
    where_parts.append(
        "EXISTS ("
        "SELECT 1 FROM dws_interaction_detail interaction_channel "
        f"WHERE interaction_channel.customer_name = {customer_name_column} "
        f"AND {' AND '.join(channel_parts)}"
        ")"
    )


def channel_group_case(
    column: str,
    params: MutableMapping[str, Any],
    *,
    prefix: str = "channel_group",
) -> str:
    """Return a CASE expression that groups raw channels into UI categories."""
    clauses = [
        "CASE",
        f"WHEN {column} IS NULL OR TRIM({column}) = '' THEN '{UNREACHED_CHANNEL}'",
    ]
    for canonical, aliases in CHANNEL_ALIASES.items():
        placeholders = _bind_values(
            params,
            aliases,
            prefix=f"{prefix}_{canonical}",
        )
        clauses.append(f"WHEN {column} IN ({placeholders}) THEN '{canonical}'")
    clauses.append(f"ELSE '{OTHER_CHANNEL}' END")
    return " ".join(clauses)
