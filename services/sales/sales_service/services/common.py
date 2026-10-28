"""Helpers shared by the sales service modules."""

import unicodedata
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.audit import record_audit
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode

from ..models import KnownBranch, OutboxEvent

SERVICE = "sales"
# Cost and margin: only for users with finance.cost_profit.
COST_FIELDS = frozenset({"cost", "cost_per_base", "cost_total", "margin"})


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
    record_audit(session, OutboxEvent, service=SERVICE, action=action, entity_type=entity_type,
                 entity_id=entity_id, actor=actor, branch_id=branch_id, before=before, after=after)  # fmt: skip


async def branch_for(session: AsyncSession, actor: CurrentUser, branch_id: UUID) -> KnownBranch:
    actor.require_branch(branch_id)
    branch = await session.get(KnownBranch, branch_id)
    if branch is None or not branch.is_active:
        raise AppError(ErrorCode.UNKNOWN_BRANCH, "Unknown or inactive branch", status_code=422)
    return branch
