"""Spreadsheet safety shared by every export (docs/spec.md → Injection and input
attacks → Spreadsheet formula injection).

A cell whose text starts with = + - @ (or a tab / carriage return, which some
programs strip before reading the rest) is run as a formula by Excel. Every
exported text value goes through `safe_cell`, which prefixes it with ' so it is
shown as text. Numbers are left alone, so -5 stays a number.
"""

from typing import Any

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value
