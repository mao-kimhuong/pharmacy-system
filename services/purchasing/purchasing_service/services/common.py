"""Helpers shared by the purchasing service modules."""

import unicodedata
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.audit import record_audit
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode

from ..models import KnownBranch, OutboxEvent, Product, ProductPackUnit

SERVICE = "purchasing"
# Prices paid to suppliers. Shown only to users who buy or pay (or see cost):
# a cashier receiving goods sees quantities, lots and expiry, not prices.
COST_FIELDS = frozenset({"unit_cost", "cost_per_base", "line_total", "total", "paid", "balance"})


def can_see_cost(user: CurrentUser) -> bool:
    return user.has_any("purchasing.order", "purchasing.pay", "finance.cost_profit")


def clean(value: Any) -> str:
    if value is None:
        return ""
    return unicodedata.normalize("NFC", str(value)).strip()


def not_found(what: str) -> AppError:
    return AppError(ErrorCode.NOT_FOUND, f"{what} not found", status_code=404)


def audit(
    session: AsyncSession,
    actor: CurrentUser,
    action: str,
    entity_type: str,
    entity_id: UUID,
    *,
    branch_id: UUID | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    record_audit(
        session, OutboxEvent, service=SERVICE, action=action, entity_type=entity_type, entity_id=entity_id,
        actor=actor, branch_id=branch_id, before=before, after=after,
    )  # fmt: skip


async def branch_for(session: AsyncSession, actor: CurrentUser, branch_id: UUID) -> KnownBranch:
    """An active branch the user works in (from the local copy of branches)."""
    actor.require_branch(branch_id)
    branch = await session.get(KnownBranch, branch_id)
    if branch is None or not branch.is_active:
        raise AppError(ErrorCode.UNKNOWN_BRANCH, "Unknown or inactive branch", status_code=422)
    return branch


async def pack_unit_for(
    session: AsyncSession, medicine_id: UUID, pack_unit_id: UUID, *, line: int | None = None
) -> ProductPackUnit:
    """An active pack unit of an active medicine (from the local copy of the catalog)."""
    pack = (
        await session.execute(select(ProductPackUnit).where(ProductPackUnit.id == pack_unit_id))
    ).scalar_one_or_none()
    details = {"line": line} if line is not None else {}
    if pack is None or pack.product_id != medicine_id:
        raise AppError(
            ErrorCode.UNKNOWN_MEDICINE, "Unknown medicine or pack unit", status_code=422, details=details
        )
    if not (pack.is_active and pack.product.is_active):
        raise AppError(
            ErrorCode.UNKNOWN_MEDICINE, f"{pack.product.sku} ({pack.name}) is deactivated", status_code=422,
            details=details,
        )  # fmt: skip
    return pack


async def products_by_id(session: AsyncSession, ids: set[UUID]) -> dict[UUID, Product]:
    rows = (await session.execute(select(Product).where(Product.id.in_(ids)))).scalars()
    return {p.id: p for p in rows}


async def commit(session: AsyncSession, conflicts: dict[str, tuple[ErrorCode, str]] | None = None) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        text = str(exc.orig)
        for constraint, (code, message) in (conflicts or {}).items():
            if constraint in text:
                raise AppError(code, message, status_code=409) from exc
        raise
