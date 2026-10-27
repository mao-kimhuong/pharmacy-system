"""Hiding fields a user may not see (docs/spec.md: cost and profit are visible
to the owner, and to others only if granted).

Routes build the full response, then drop the hidden keys before returning,
so the response looks the same minus those fields (not null: absent).
"""

from typing import Any


def drop_fields(data: Any, fields: frozenset[str] | set[str]) -> Any:
    """Copy of `data` (dicts / lists, any depth) without the given keys."""
    if isinstance(data, dict):
        return {k: drop_fields(v, fields) for k, v in data.items() if k not in fields}
    if isinstance(data, list):
        return [drop_fields(v, fields) for v in data]
    return data
