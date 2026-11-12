"""Settings → User Log.

The auth service writes its own entries directly (same transaction as the
change). Entries from other services arrive as `audit.recorded` events and are
stored by `store_event`. Never log secrets: use User.safe_fields().
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.audit import changes
from pharmacy_shared.auth import CurrentUser

from ..models import AuditLog


def write_audit(
    session: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: UUID | str | None,
    actor: CurrentUser | None = None,
    actor_id: UUID | None = None,
    actor_role: str | None = None,
    branch_id: UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip: str | None = None,
    only_changes: bool = True,
) -> None:
    before = before or {}
    after = after or {}
    if only_changes and before and after:
        before, after = changes(before, after)
    session.add(
        AuditLog(
            service="auth",
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            actor_id=actor.id if actor else actor_id,
            actor_role=actor.role if actor else actor_role,
            branch_id=branch_id,
            before=before,
            after=after,
            ip=ip,
        )
    )


def _seeded_time(payload: dict[str, Any]) -> dict[str, Any]:
    """Only events sent under the dev clock (development seed) carry occurred_at: keep their time."""
    from datetime import datetime

    try:
        return {"occurred_at": datetime.fromisoformat(payload["occurred_at"])} if payload.get("occurred_at") else {}
    except (TypeError, ValueError):
        return {}


async def store_event(session: AsyncSession, payload: dict[str, Any], message_id: UUID) -> None:
    """An `audit.recorded` event from another service."""

    def uuid_or_none(value: Any) -> UUID | None:
        try:
            return UUID(str(value)) if value else None
        except ValueError:
            return None

    session.add(
        AuditLog(
            service=str(payload.get("service", "unknown"))[:32],
            action=str(payload.get("action", "unknown"))[:64],
            entity_type=str(payload.get("entity_type", "unknown"))[:40],
            entity_id=(str(payload["entity_id"])[:64] if payload.get("entity_id") else None),
            actor_id=uuid_or_none(payload.get("actor_id")),
            actor_role=(str(payload["actor_role"])[:32] if payload.get("actor_role") else None),
            branch_id=uuid_or_none(payload.get("branch_id")),
            before=payload.get("before") or {},
            after=payload.get("after") or {},
            ip=(str(payload["ip"])[:64] if payload.get("ip") else None),
            message_id=message_id,
            **_seeded_time(payload),
        )
    )


def _filtered(
    query: Select,
    actor: CurrentUser,
    *,
    actor_id: UUID | None,
    branch_id: UUID | None,
    action: str | None,
    entity_type: str | None,
    entity_id: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> Select:
    if not actor.is_owner:
        # Managers see only entries of their own branches.
        query = query.where(AuditLog.branch_id.in_(actor.branch_ids or [UUID(int=0)]))
    if actor_id:
        query = query.where(AuditLog.actor_id == actor_id)
    if branch_id:
        query = query.where(AuditLog.branch_id == branch_id)
    if action:
        query = query.where(AuditLog.action == action)
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    if entity_id:
        query = query.where(AuditLog.entity_id == entity_id)
    if date_from:
        query = query.where(AuditLog.occurred_at >= date_from)
    if date_to:
        query = query.where(AuditLog.occurred_at < date_to)
    return query


async def list_audit(
    session: AsyncSession, actor: CurrentUser, *, page: int, size: int, **filters: Any
) -> tuple[list[AuditLog], int]:
    rows = await session.execute(
        _filtered(select(AuditLog), actor, **filters)
        .order_by(AuditLog.seq.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    total = await session.execute(_filtered(select(func.count(AuditLog.id)), actor, **filters))
    return list(rows.scalars()), int(total.scalar_one())
