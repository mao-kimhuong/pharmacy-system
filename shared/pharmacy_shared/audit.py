"""User Log (audit) events.

Every service records changes with `record_audit(...)` inside the same
transaction as the change. It writes an `audit.recorded` event to the outbox;
the auth service consumes it into the `audit_logs` table (Settings → User Log).

Never put passwords, PIN, TOTP secrets or tokens in `before` / `after`.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from .auth import CurrentUser
from .outbox import add_event

AUDIT_EVENT = "audit.recorded"


def changes(before: dict[str, Any], after: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Keep only the fields that changed, so the log shows what really moved."""
    keys = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    return {k: before.get(k) for k in keys}, {k: after.get(k) for k in keys}


def audit_payload(
    *,
    service: str,
    action: str,
    entity_type: str,
    entity_id: UUID | str | None,
    actor: CurrentUser | None,
    branch_id: UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip: str | None = None,
) -> dict[str, Any]:
    return {
        "service": service,
        "action": action,
        "entity_type": entity_type,
        "entity_id": str(entity_id) if entity_id is not None else None,
        "actor_id": str(actor.id) if actor else None,
        "actor_role": actor.role if actor else None,
        "branch_id": str(branch_id) if branch_id else None,
        "before": before or {},
        "after": after or {},
        "ip": ip,
    }


def record_audit(session: AsyncSession, outbox_model: type, **kwargs: Any) -> None:
    """Queue an audit entry in the current transaction (see audit_payload for fields)."""
    add_event(session, outbox_model, AUDIT_EVENT, audit_payload(**kwargs))
