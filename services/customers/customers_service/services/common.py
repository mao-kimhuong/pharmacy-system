"""Helpers shared by the customers service modules."""

import unicodedata
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.audit import record_audit
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.internal import InternalCaller

from ..models import KnownBranch, LedgerEntry, OutboxEvent

SERVICE = "customers"
ZERO = Decimal("0.00")


def clean(value: Any) -> str:
    if value is None:
        return ""
    return unicodedata.normalize("NFC", str(value)).strip()


def not_found(what: str) -> AppError:
    return AppError(ErrorCode.NOT_FOUND, f"{what} not found", status_code=404)


def acting_user(caller: InternalCaller) -> CurrentUser | None:
    """The user a service called for, for the User Log."""
    if caller.user_id is None:
        return None
    return CurrentUser(id=caller.user_id, role=caller.role or "", branch_ids=frozenset(), is_pharmacist=False)


def audit(
    session: AsyncSession, actor: CurrentUser | None, action: str, entity_type: str, entity_id: Any,
    *, branch_id: UUID | None = None, before: dict | None = None, after: dict | None = None,
) -> None:  # fmt: skip
    record_audit(session, OutboxEvent, service=SERVICE, action=action, entity_type=entity_type,
                 entity_id=entity_id, actor=actor, branch_id=branch_id, before=before, after=after)  # fmt: skip


async def balance_of(session: AsyncSession, customer_id: UUID) -> Decimal:
    total = (
        await session.execute(select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
            LedgerEntry.customer_id == customer_id))
    ).scalar_one()  # fmt: skip
    return Decimal(total).quantize(Decimal("0.01"))


async def branch_for(session: AsyncSession, actor: CurrentUser, branch_id: UUID) -> KnownBranch:
    actor.require_branch(branch_id)
    branch = await session.get(KnownBranch, branch_id)
    if branch is None or not branch.is_active:
        raise AppError(ErrorCode.UNKNOWN_BRANCH, "Unknown or inactive branch", status_code=422)
    return branch
