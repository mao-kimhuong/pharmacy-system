"""Categories and brands. Rules:

- Never deleted: deactivate (with a reason) / activate.
- The English name is unique, ignoring case (the Excel import matches on it).
- Every change: a category.* / brand.* event and a User Log entry.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.audit import changes, record_audit
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.outbox import add_event

from ..models import Brand, Category, OutboxEvent
from .common import SERVICE, clean, commit, not_found

Lookup = Category | Brand
KINDS: dict[str, type[Category] | type[Brand]] = {"category": Category, "brand": Brand}


def kind_of(model: type) -> str:
    return "category" if model is Category else "brand"


def event_payload(row: Lookup) -> dict[str, Any]:
    return {"id": str(row.id), "name_km": row.name_km, "name_en": row.name_en, "is_active": row.is_active}


def audit(
    session: AsyncSession, actor: CurrentUser, action: str, row: Lookup, before: dict, after: dict
) -> None:
    record_audit(
        session,
        OutboxEvent,
        service=SERVICE,
        action=action,
        entity_type=kind_of(type(row)),
        entity_id=row.id,
        actor=actor,
        before=before,
        after=after,
    )


async def find_by_name(session: AsyncSession, model: type, name_en: str) -> Lookup | None:
    query = select(model).where(func.lower(model.name_en) == clean(name_en).lower())
    return (await session.execute(query)).scalar_one_or_none()


async def _check_name_free(session: AsyncSession, model: type, name_en: str, exclude: UUID | None) -> None:
    existing = await find_by_name(session, model, name_en)
    if existing is not None and existing.id != exclude:
        raise AppError(
            ErrorCode.DUPLICATE_NAME,
            f"A {kind_of(model)} named {existing.name_en!r} already exists",
            status_code=409,
        )


async def list_rows(session: AsyncSession, model: type, include_inactive: bool) -> list[Lookup]:
    query = select(model).order_by(func.lower(model.name_en))
    if not include_inactive:
        query = query.where(model.is_active.is_(True))
    return list((await session.execute(query)).scalars())


async def get_row(session: AsyncSession, model: type, row_id: UUID, *, lock: bool = False) -> Lookup:
    query = select(model).where(model.id == row_id)
    if lock:
        query = query.with_for_update()
    row = (await session.execute(query)).scalar_one_or_none()
    if row is None:
        raise not_found(kind_of(model).capitalize())
    return row


def new_row(model: type, actor: CurrentUser, name_en: str, name_km: str = "") -> Lookup:
    return model(name_en=clean(name_en), name_km=clean(name_km), created_by=actor.id)


def record_created(session: AsyncSession, actor: CurrentUser, row: Lookup, **extra: Any) -> None:
    kind = kind_of(type(row))
    add_event(session, OutboxEvent, f"{kind}.created", event_payload(row))
    audit(session, actor, f"{kind}.created", row, {}, {**row.safe_fields(), **extra})


async def create_row(session: AsyncSession, actor: CurrentUser, model: type, data: dict[str, Any]) -> Lookup:
    await _check_name_free(session, model, data["name_en"], None)
    row = new_row(model, actor, data["name_en"], data.get("name_km") or "")
    session.add(row)
    await session.flush()
    record_created(session, actor, row)
    await commit(session)
    return row


async def update_row(
    session: AsyncSession, actor: CurrentUser, model: type, row_id: UUID, data: dict[str, Any]
) -> Lookup:
    row = await get_row(session, model, row_id, lock=True)
    before = row.safe_fields()
    if data.get("name_en") is not None:
        await _check_name_free(session, model, data["name_en"], row.id)
        row.name_en = clean(data["name_en"])
    if data.get("name_km") is not None:
        row.name_km = clean(data["name_km"])
    after = row.safe_fields()
    if after != before:
        kind = kind_of(model)
        add_event(session, OutboxEvent, f"{kind}.updated", event_payload(row))
        audit(session, actor, f"{kind}.updated", row, *changes(before, after))
    await commit(session)
    return row


async def set_active(
    session: AsyncSession, actor: CurrentUser, model: type, row_id: UUID, active: bool, reason: str | None
) -> Lookup:
    """Medicines that use it keep it; it is only hidden from pick lists."""
    row = await get_row(session, model, row_id, lock=True)
    if row.is_active == active:
        return row
    row.is_active = active
    kind = kind_of(model)
    action = f"{kind}.activated" if active else f"{kind}.deactivated"
    add_event(session, OutboxEvent, action, event_payload(row))
    audit(session, actor, action, row, {"is_active": not active}, {"is_active": active, "reason": reason})
    await commit(session)
    return row
