"""Events the stockcount service listens to (queue `stockcount.events`).

- branch.*                → branches (codes for numbers)
- branch.settings_updated → double-count and owner-approval limits
"""

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import copies

from ..models import BranchSettingsCopy, KnownBranch

ROUTING_KEYS = ("branch.*",)


async def handle_event(
    session: AsyncSession, event_type: str, payload: dict[str, Any], message_id: UUID
) -> None:
    if event_type in copies.BRANCH_EVENTS:
        await copies.upsert_branch(session, KnownBranch, payload)
    elif event_type == "branch.settings_updated":
        values = {
            "branch_id": UUID(payload["branch_id"]),
            "double_count_above_usd": Decimal(str(payload.get("double_count_above_usd") or "50")),
            "owner_approval_above_usd": Decimal(str(payload.get("owner_approval_above_usd") or "200")),
        }
        await session.execute(insert(BranchSettingsCopy).values(**values).on_conflict_do_update(
            index_elements=[BranchSettingsCopy.branch_id], set_={k: v for k, v in values.items() if k != "branch_id"}))  # fmt: skip
