"""Doctors. Never deleted: deactivate. Licence numbers are unique. Shared by all
branches. Every change: doctor.* event + User Log entry."""

from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.audit import changes
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.outbox import add_event
from pharmacy_shared.phone import normalize_phone

from ..models import Doctor, OutboxEvent
from .common import audit, clean, not_found


def _phone(raw: str | None) -> str:
    if not clean(raw):
        return ""
    try:
        return normalize_phone(raw)
    except ValueError as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Not a phone number", status_code=422) from exc


def _event(session: AsyncSession, action: str, d: Doctor) -> None:
    add_event(session, OutboxEvent, action, {"doctor_id": str(d.id), **d.safe_fields()})


async def _licence_free(session: AsyncSession, licence: str, exclude: UUID | None) -> None:
    found = (
        await session.execute(select(Doctor.id).where(func.upper(Doctor.licence_no) == licence.upper()))
    ).scalar_one_or_none()
    if found is not None and found != exclude:
        raise AppError(ErrorCode.DUPLICATE_CODE, "Another doctor has this licence number", status_code=409)


async def get_doctor(session: AsyncSession, doctor_id: UUID, *, lock: bool = False) -> Doctor:
    query = select(Doctor).where(Doctor.id == doctor_id)
    d = (await session.execute(query.with_for_update() if lock else query)).scalar_one_or_none()
    if d is None:
        raise not_found("Doctor")
    return d


async def list_doctors(session: AsyncSession, q: str | None, include_inactive: bool, page: int, size: int):  # noqa: ANN201
    query = select(Doctor)
    if q and clean(q):
        like = "%" + clean(q).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.where(or_(Doctor.name.ilike(like, escape="\\"), Doctor.licence_no.ilike(like, escape="\\"),
                                Doctor.clinic.ilike(like, escape="\\")))  # fmt: skip
    if not include_inactive:
        query = query.where(Doctor.is_active.is_(True))
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = await session.execute(
        query.order_by(func.lower(Doctor.name), Doctor.id).offset((page - 1) * size).limit(size)
    )
    return list(rows.scalars()), int(total)


async def create_doctor(session: AsyncSession, actor: CurrentUser, data: dict[str, Any]) -> Doctor:
    licence = clean(data["licence_no"])
    await _licence_free(session, licence, None)
    d = Doctor(name=clean(data["name"]), licence_no=licence, specialty=clean(data.get("specialty")),
               clinic=clean(data.get("clinic")), phone=_phone(data.get("phone")), created_by=actor.id)  # fmt: skip
    session.add(d)
    await session.flush()
    _event(session, "doctor.created", d)
    audit(session, actor, "doctor.created", "doctor", d.id, after=d.safe_fields())
    await session.commit()
    return d


async def update_doctor(
    session: AsyncSession, actor: CurrentUser, doctor_id: UUID, data: dict[str, Any]
) -> Doctor:
    d = await get_doctor(session, doctor_id, lock=True)
    before = d.safe_fields()
    if data.get("licence_no") is not None:
        await _licence_free(session, clean(data["licence_no"]), d.id)
        d.licence_no = clean(data["licence_no"])
    for f in ("name", "specialty", "clinic"):
        if data.get(f) is not None:
            setattr(d, f, clean(data[f]))
    if data.get("phone") is not None:
        d.phone = _phone(data["phone"])
    if d.safe_fields() != before:
        _event(session, "doctor.updated", d)
        old, new = changes(before, d.safe_fields())
        audit(session, actor, "doctor.updated", "doctor", d.id, before=old, after=new)
    await session.commit()
    return d


async def set_active(
    session: AsyncSession, actor: CurrentUser, doctor_id: UUID, active: bool, reason: str | None
) -> Doctor:
    d = await get_doctor(session, doctor_id, lock=True)
    if d.is_active != active:
        d.is_active = active
        action = "doctor.activated" if active else "doctor.deactivated"
        _event(session, action, d)
        audit(session, actor, action, "doctor", d.id, before={"is_active": not active},
              after={"is_active": active, **({"reason": reason} if reason else {})})  # fmt: skip
        await session.commit()
    return d
