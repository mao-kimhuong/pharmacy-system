"""Suppliers and supplier groups. Rules:

- Never deleted: deactivate (with a reason) / activate.
- Supplier codes are unique (capital letters, digits, - _), fixed after creation.
- Group English names are unique, ignoring case.
- Supplier groups are hidden in the menu by the supplier_groups feature switch;
  the API always works.
- Every change: supplier.* / supplier_group.* event + User Log entry.
"""

import re
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.audit import changes
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.outbox import add_event

from ..models import OutboxEvent, Supplier, SupplierGroup
from .common import audit, clean, commit, not_found

_CODE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,19}$")
_TEXT = ("name", "name_km", "phone", "address")


def supplier_payload(s: Supplier) -> dict[str, Any]:
    return {
        "supplier_id": str(s.id), "code": s.code, "name": s.name, "name_km": s.name_km,
        "phone": s.phone, "address": s.address, "payment_terms_days": s.payment_terms_days,
        "is_active": s.is_active,
    }  # fmt: skip


# ---------------------------------------------------------------- groups


async def list_groups(session: AsyncSession, include_inactive: bool) -> list[SupplierGroup]:
    query = select(SupplierGroup).order_by(func.lower(SupplierGroup.name_en))
    if not include_inactive:
        query = query.where(SupplierGroup.is_active.is_(True))
    return list((await session.execute(query)).scalars())


async def get_group(session: AsyncSession, group_id: UUID, *, lock: bool = False) -> SupplierGroup:
    query = select(SupplierGroup).where(SupplierGroup.id == group_id)
    group = (await session.execute(query.with_for_update() if lock else query)).scalar_one_or_none()
    if group is None:
        raise not_found("Supplier group")
    return group


async def _check_group_name(session: AsyncSession, name_en: str, exclude: UUID | None) -> None:
    found = (
        await session.execute(
            select(SupplierGroup.id).where(func.lower(SupplierGroup.name_en) == clean(name_en).lower())
        )
    ).scalar_one_or_none()
    if found is not None and found != exclude:
        raise AppError(
            ErrorCode.DUPLICATE_NAME, "A supplier group with this name already exists", status_code=409
        )


def _group_event(session: AsyncSession, action: str, g: SupplierGroup) -> None:
    add_event(session, OutboxEvent, action, {"group_id": str(g.id), **g.safe_fields()})


async def create_group(session: AsyncSession, actor: CurrentUser, data: dict[str, Any]) -> SupplierGroup:
    await _check_group_name(session, data["name_en"], None)
    g = SupplierGroup(name_en=clean(data["name_en"]), name_km=clean(data.get("name_km")), created_by=actor.id)
    session.add(g)
    await session.flush()
    _group_event(session, "supplier_group.created", g)
    audit(session, actor, "supplier_group.created", "supplier_group", g.id, after=g.safe_fields())
    await commit(session)
    return g


async def update_group(
    session: AsyncSession, actor: CurrentUser, group_id: UUID, data: dict[str, Any]
) -> SupplierGroup:
    g = await get_group(session, group_id, lock=True)
    before = g.safe_fields()
    if data.get("name_en") is not None:
        await _check_group_name(session, data["name_en"], g.id)
        g.name_en = clean(data["name_en"])
    if data.get("name_km") is not None:
        g.name_km = clean(data["name_km"])
    if g.safe_fields() != before:
        _group_event(session, "supplier_group.updated", g)
        old, new = changes(before, g.safe_fields())
        audit(session, actor, "supplier_group.updated", "supplier_group", g.id, before=old, after=new)
    await commit(session)
    return g


async def set_group_active(
    session: AsyncSession, actor: CurrentUser, group_id: UUID, active: bool, reason: str | None
) -> SupplierGroup:
    g = await get_group(session, group_id, lock=True)
    if g.is_active != active:
        g.is_active = active
        action = "supplier_group.activated" if active else "supplier_group.deactivated"
        _group_event(session, action, g)
        audit(session, actor, action, "supplier_group", g.id, before={"is_active": not active},
              after={"is_active": active, **({"reason": reason} if reason else {})})  # fmt: skip
        await commit(session)
    return g


# ---------------------------------------------------------------- suppliers


async def list_suppliers(
    session: AsyncSession, q: str | None, group_id: UUID | None, include_inactive: bool, page: int, size: int
) -> tuple[list[Supplier], int]:
    query = select(Supplier)
    if q and clean(q):
        like = "%" + clean(q).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.where(or_(Supplier.name.ilike(like, escape="\\"), Supplier.code.ilike(like, escape="\\"),
                                Supplier.name_km.ilike(like, escape="\\"), Supplier.phone.ilike(like, escape="\\")))  # fmt: skip
    if group_id:
        query = query.where(Supplier.group_id == group_id)
    if not include_inactive:
        query = query.where(Supplier.is_active.is_(True))
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = await session.execute(
        query.order_by(func.lower(Supplier.name), Supplier.id).offset((page - 1) * size).limit(size)
    )
    return list(rows.scalars()), int(total)


async def get_supplier(session: AsyncSession, supplier_id: UUID, *, lock: bool = False) -> Supplier:
    query = select(Supplier).where(Supplier.id == supplier_id)
    s = (await session.execute(query.with_for_update() if lock else query)).scalar_one_or_none()
    if s is None:
        raise not_found("Supplier")
    return s


async def active_supplier(session: AsyncSession, supplier_id: UUID) -> Supplier:
    s = await session.get(Supplier, supplier_id)
    if s is None or not s.is_active:
        raise AppError(ErrorCode.UNKNOWN_SUPPLIER, "Unknown or inactive supplier", status_code=422)
    return s


async def _group_for(session: AsyncSession, group_id: UUID | None) -> SupplierGroup | None:
    if group_id is None:
        return None
    g = await session.get(SupplierGroup, group_id)
    if g is None or not g.is_active:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Unknown or inactive supplier group", status_code=422,
                       details={"field": "group_id"})  # fmt: skip
    return g


def _event(session: AsyncSession, action: str, s: Supplier) -> None:
    add_event(session, OutboxEvent, action, supplier_payload(s))


async def create_supplier(session: AsyncSession, actor: CurrentUser, data: dict[str, Any]) -> Supplier:
    code = clean(data["code"]).upper()
    if not _CODE.match(code):
        raise AppError(ErrorCode.VALIDATION_ERROR, "Code: 2-20 capital letters, digits, - or _ (e.g. DKSH)",
                       status_code=422, details={"field": "code"})  # fmt: skip
    if (await session.execute(select(Supplier.id).where(Supplier.code == code))).first():
        raise AppError(ErrorCode.DUPLICATE_CODE, f"Supplier code {code} is already used", status_code=409)
    s = Supplier(code=code, payment_terms_days=data.get("payment_terms_days") or 0, created_by=actor.id,
                 **{f: clean(data.get(f)) for f in _TEXT})  # fmt: skip
    s.group = await _group_for(session, data.get("group_id"))
    session.add(s)
    await session.flush()
    _event(session, "supplier.created", s)
    audit(session, actor, "supplier.created", "supplier", s.id, after=s.safe_fields())
    await commit(session, {"suppliers_code_key": (ErrorCode.DUPLICATE_CODE, "Supplier code is already used")})
    return s


async def update_supplier(
    session: AsyncSession, actor: CurrentUser, supplier_id: UUID, data: dict[str, Any]
) -> Supplier:
    s = await get_supplier(session, supplier_id, lock=True)
    before = s.safe_fields()
    for f in _TEXT:
        if data.get(f) is not None:
            setattr(s, f, clean(data[f]))
    if data.get("payment_terms_days") is not None:
        s.payment_terms_days = data["payment_terms_days"]
    if "group_id" in data:
        s.group = await _group_for(session, data["group_id"])
    after = s.safe_fields()
    if after != before:
        _event(session, "supplier.updated", s)
        audit(session, actor, "supplier.updated", "supplier", s.id, before=changes(before, after)[0],
              after=changes(before, after)[1])  # fmt: skip
    await commit(session)
    return s


async def set_supplier_active(
    session: AsyncSession, actor: CurrentUser, supplier_id: UUID, active: bool, reason: str | None
) -> Supplier:
    """A deactivated supplier keeps its POs, bills and payments; no new POs."""
    s = await get_supplier(session, supplier_id, lock=True)
    if s.is_active != active:
        s.is_active = active
        action = "supplier.activated" if active else "supplier.deactivated"
        _event(session, action, s)
        audit(session, actor, action, "supplier", s.id, before={"is_active": not active},
              after={"is_active": active, **({"reason": reason} if reason else {})})  # fmt: skip
        await commit(session)
    return s
