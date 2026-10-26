"""Events the auth service listens to (RabbitMQ queue `auth.events`).

- audit.recorded   → a User Log entry from another service
- branch.*         → local copy of branches, used when assigning staff
"""

from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.audit import AUDIT_EVENT

from ..models import KnownBranch
from .audit import store_event

ROUTING_KEYS = (AUDIT_EVENT, "branch.*")


async def handle_event(
    session: AsyncSession, event_type: str, payload: dict[str, Any], message_id: UUID
) -> None:
    if event_type == AUDIT_EVENT:
        await store_event(session, payload, message_id)
    elif event_type in ("branch.created", "branch.updated", "branch.activated", "branch.deactivated"):
        values = {
            "id": UUID(str(payload["branch_id"])),
            "code": str(payload["code"]),
            "name_en": str(payload["name_en"]),
            "is_active": bool(payload["is_active"]),
        }
        await session.execute(
            insert(KnownBranch)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[KnownBranch.id], set_={k: v for k, v in values.items() if k != "id"}
            )
        )
