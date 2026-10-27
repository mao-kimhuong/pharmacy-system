"""Helpers used by every catalog service module."""

import re
import unicodedata
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.errors import AppError, ErrorCode

SERVICE = "catalog"
SKU_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._\-/]{0,39}$")

# Unique constraint / index name → (error code, message)
_CONFLICTS = {
    "medicines_sku_key": (ErrorCode.DUPLICATE_SKU, "Another medicine already has this SKU"),
    "pack_units_barcode_key": (ErrorCode.DUPLICATE_BARCODE, "Another pack unit already has this barcode"),
    "uq_pack_units_name": (ErrorCode.DUPLICATE_NAME, "This medicine already has a pack unit with this name"),
    "uq_categories_name_en": (ErrorCode.DUPLICATE_NAME, "A category with this name already exists"),
    "uq_brands_name_en": (ErrorCode.DUPLICATE_NAME, "A brand with this name already exists"),
}


def clean(value: Any) -> str:
    """Trimmed text in Unicode NFC, so Khmer typed on different keyboards
    compares and searches the same."""
    if value is None:
        return ""
    return unicodedata.normalize("NFC", str(value)).strip()


def clean_sku(value: Any) -> str:
    sku = clean(value).upper()
    if not SKU_PATTERN.match(sku):
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "SKU: 1-40 capital letters, digits or . _ - / (e.g. PARA500)",
            status_code=422,
            details={"field": "sku"},
        )
    return sku


def escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def not_found(what: str) -> AppError:
    return AppError(ErrorCode.NOT_FOUND, f"{what} not found", status_code=404)


def conflict_from(exc: IntegrityError) -> AppError | None:
    """Turn a unique-constraint race (two people saving at once) into a 409."""
    orig = exc.orig
    name = getattr(getattr(orig, "__cause__", None), "constraint_name", None) or ""
    text = f"{name} {orig}"
    for constraint, (code, message) in _CONFLICTS.items():
        if constraint in text:
            return AppError(code, message, status_code=409)
    return None


async def commit(session: AsyncSession) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        error = conflict_from(exc)
        if error is None:
            raise
        raise error from exc
