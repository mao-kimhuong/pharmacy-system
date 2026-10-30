"""Helpers shared by the inventory service modules."""

import unicodedata
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.audit import record_audit
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode

from ..config import get_settings
from ..models import KnownBranch, KnownSupplier, OutboxEvent, ProductPackUnit

SERVICE = "inventory"
# Cost and stock value: only for users with finance.cost_profit (docs/spec.md).
COST_FIELDS = frozenset({"cost_per_base", "unit_cost", "value", "stock_value", "last_cost_per_base"})


def can_see_cost(user: CurrentUser) -> bool:
    return user.has("finance.cost_profit")


def clean(value: Any) -> str:
    if value is None:
        return ""
    return unicodedata.normalize("NFC", str(value)).strip()


def audit(
    session: AsyncSession, actor: CurrentUser | None, action: str, entity_type: str, entity_id: Any,
    *, branch_id: UUID | None = None, before: dict | None = None, after: dict | None = None,
) -> None:  # fmt: skip
    record_audit(
        session, OutboxEvent, service=SERVICE, action=action, entity_type=entity_type, entity_id=entity_id,
        actor=actor, branch_id=branch_id, before=before, after=after,
    )  # fmt: skip


async def branch_for(session: AsyncSession, actor: CurrentUser, branch_id: UUID) -> KnownBranch:
    actor.require_branch(branch_id)
    branch = await session.get(KnownBranch, branch_id)
    if branch is None or not branch.is_active:
        raise AppError(ErrorCode.UNKNOWN_BRANCH, "Unknown or inactive branch", status_code=422)
    return branch


async def supplier_for(session: AsyncSession, supplier_id: UUID | None) -> KnownSupplier | None:
    if supplier_id is None:
        return None
    supplier = await session.get(KnownSupplier, supplier_id)
    if supplier is None or not supplier.is_active:
        raise AppError(ErrorCode.UNKNOWN_SUPPLIER, "Unknown or inactive supplier", status_code=422)
    return supplier


async def find_pack_unit(
    session: AsyncSession, medicine_id: UUID, pack_unit_id: UUID
) -> ProductPackUnit | None:
    pack = (
        await session.execute(select(ProductPackUnit).where(ProductPackUnit.id == pack_unit_id))
    ).scalar_one_or_none()
    if pack is None or pack.product_id != medicine_id:
        return None
    return pack


def expiry_problem(expiry: date, today: date | None = None) -> str | None:
    """None if the expiry is acceptable; else why not."""
    today = today or clock.today()
    if expiry < today:
        return f"expired on {expiry}"
    return None


def is_short_expiry(expiry: date, today: date | None = None) -> bool:
    today = today or clock.today()
    return expiry < today + timedelta(days=get_settings().short_expiry_days)
