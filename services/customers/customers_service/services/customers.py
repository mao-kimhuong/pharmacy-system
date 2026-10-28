"""Customers and customer groups. Rules:

- Phone numbers are unique, stored normalized (0XXXXXXXX), like staff phones.
- Never deleted: deactivate (with a reason) / activate.
- Setting or changing a credit limit needs customers.credit_limit (owner and
  branch manager): a cashier can add customers, but only with no credit.
- Customer groups (menu hidden by the customer_groups switch) carry a default
  discount %, stored now and applied by sales in S7.
- Every change: customer.* / customer_group.* event + User Log entry.
"""

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.audit import changes
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.outbox import add_event
from pharmacy_shared.phone import normalize_phone

from ..models import Customer, CustomerGroup, OutboxEvent
from .common import audit, clean, not_found

CREDIT_PERMISSION = "customers.credit_limit"
CENT = Decimal("0.01")


def _money(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT)


def customer_payload(c: Customer) -> dict[str, Any]:
    return {
        "customer_id": str(c.id), "phone": c.phone, "name": c.name, "name_km": c.name_km,
        "group_id": str(c.group_id) if c.group_id else None, "credit_limit": str(c.credit_limit),
        "is_active": c.is_active,
    }  # fmt: skip


def _phone(raw: str) -> str:
    try:
        return normalize_phone(raw)
    except ValueError as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Not a phone number", status_code=422,
                       details={"field": "phone"}) from exc  # fmt: skip


async def _check_phone_free(session: AsyncSession, phone: str, exclude: UUID | None) -> None:
    found = (await session.execute(select(Customer.id).where(Customer.phone == phone))).scalar_one_or_none()
    if found is not None and found != exclude:
        raise AppError(ErrorCode.DUPLICATE_PHONE, "Another customer has this phone number", status_code=409)


# ---------------------------------------------------------------- groups


async def list_groups(session: AsyncSession, include_inactive: bool) -> list[CustomerGroup]:
    query = select(CustomerGroup).order_by(func.lower(CustomerGroup.name_en))
    if not include_inactive:
        query = query.where(CustomerGroup.is_active.is_(True))
    return list((await session.execute(query)).scalars())


async def get_group(session: AsyncSession, group_id: UUID, *, lock: bool = False) -> CustomerGroup:
    query = select(CustomerGroup).where(CustomerGroup.id == group_id)
    g = (await session.execute(query.with_for_update() if lock else query)).scalar_one_or_none()
    if g is None:
        raise not_found("Customer group")
    return g


async def _check_group_name(session: AsyncSession, name_en: str, exclude: UUID | None) -> None:
    found = (await session.execute(select(CustomerGroup.id).where(
        func.lower(CustomerGroup.name_en) == clean(name_en).lower()))).scalar_one_or_none()  # fmt: skip
    if found is not None and found != exclude:
        raise AppError(
            ErrorCode.DUPLICATE_NAME, "A customer group with this name already exists", status_code=409
        )


def _group_event(session: AsyncSession, action: str, g: CustomerGroup) -> None:
    add_event(session, OutboxEvent, action, {"group_id": str(g.id), **g.safe_fields()})


async def create_group(session: AsyncSession, actor: CurrentUser, data: dict[str, Any]) -> CustomerGroup:
    await _check_group_name(session, data["name_en"], None)
    g = CustomerGroup(name_en=clean(data["name_en"]), name_km=clean(data.get("name_km")),
                      default_discount_pct=_money(data.get("default_discount_pct")),
                      created_by=actor.id)  # fmt: skip
    session.add(g)
    await session.flush()
    _group_event(session, "customer_group.created", g)
    audit(session, actor, "customer_group.created", "customer_group", g.id, after=g.safe_fields())
    await session.commit()
    return g


async def update_group(
    session: AsyncSession, actor: CurrentUser, group_id: UUID, data: dict[str, Any]
) -> CustomerGroup:
    g = await get_group(session, group_id, lock=True)
    before = g.safe_fields()
    if data.get("name_en") is not None:
        await _check_group_name(session, data["name_en"], g.id)
        g.name_en = clean(data["name_en"])
    if data.get("name_km") is not None:
        g.name_km = clean(data["name_km"])
    if data.get("default_discount_pct") is not None:
        g.default_discount_pct = _money(data["default_discount_pct"])
    if g.safe_fields() != before:
        _group_event(session, "customer_group.updated", g)
        old, new = changes(before, g.safe_fields())
        audit(session, actor, "customer_group.updated", "customer_group", g.id, before=old, after=new)
    await session.commit()
    return g


async def set_group_active(
    session: AsyncSession, actor: CurrentUser, group_id: UUID, active: bool, reason: str | None
) -> CustomerGroup:
    g = await get_group(session, group_id, lock=True)
    if g.is_active != active:
        g.is_active = active
        action = "customer_group.activated" if active else "customer_group.deactivated"
        _group_event(session, action, g)
        audit(session, actor, action, "customer_group", g.id, before={"is_active": not active},
              after={"is_active": active, **({"reason": reason} if reason else {})})  # fmt: skip
        await session.commit()
    return g


# ---------------------------------------------------------------- customers


async def list_customers(
    session: AsyncSession, q: str | None, group_id: UUID | None, include_inactive: bool, page: int, size: int
) -> tuple[list[Customer], int]:
    query = select(Customer)
    if q and clean(q):
        term = clean(q)
        like = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        conds = [Customer.name.ilike(like, escape="\\"), Customer.name_km.ilike(like, escape="\\")]
        try:
            conds.append(Customer.phone == normalize_phone(term))
        except ValueError:
            conds.append(Customer.phone.ilike(like, escape="\\"))
        query = query.where(or_(*conds))
    if group_id:
        query = query.where(Customer.group_id == group_id)
    if not include_inactive:
        query = query.where(Customer.is_active.is_(True))
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = await session.execute(query.order_by(func.lower(Customer.name), Customer.id)
                                 .offset((page - 1) * size).limit(size))  # fmt: skip
    return list(rows.scalars()), int(total)


async def get_customer(session: AsyncSession, customer_id: UUID, *, lock: bool = False) -> Customer:
    query = select(Customer).where(Customer.id == customer_id)
    c = (await session.execute(query.with_for_update() if lock else query)).scalar_one_or_none()
    if c is None:
        raise not_found("Customer")
    return c


async def _group_for(session: AsyncSession, group_id: UUID | None) -> CustomerGroup | None:
    if group_id is None:
        return None
    g = await session.get(CustomerGroup, group_id)
    if g is None or not g.is_active:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Unknown or inactive customer group", status_code=422,
                       details={"field": "group_id"})  # fmt: skip
    return g


def _event(session: AsyncSession, action: str, c: Customer) -> None:
    add_event(session, OutboxEvent, action, customer_payload(c))


async def create_customer(session: AsyncSession, actor: CurrentUser, data: dict[str, Any]) -> Customer:
    phone = _phone(data["phone"])
    await _check_phone_free(session, phone, None)
    limit = _money(data.get("credit_limit"))
    if limit > 0:
        actor.require(CREDIT_PERMISSION)
    c = Customer(phone=phone, name=clean(data["name"]), name_km=clean(data.get("name_km")),
                 credit_limit=limit, note=clean(data.get("note")), created_by=actor.id)  # fmt: skip
    c.group = await _group_for(session, data.get("group_id"))
    session.add(c)
    await session.flush()
    _event(session, "customer.created", c)
    audit(session, actor, "customer.created", "customer", c.id, after=c.safe_fields())
    await session.commit()
    return c


async def update_customer(
    session: AsyncSession, actor: CurrentUser, customer_id: UUID, data: dict[str, Any]
) -> Customer:
    c = await get_customer(session, customer_id, lock=True)
    before = c.safe_fields()
    if data.get("phone") is not None:
        phone = _phone(data["phone"])
        await _check_phone_free(session, phone, c.id)
        c.phone = phone
    for f in ("name", "name_km", "note"):
        if data.get(f) is not None:
            setattr(c, f, clean(data[f]))
    if "group_id" in data:
        c.group = await _group_for(session, data["group_id"])
    if data.get("credit_limit") is not None:
        limit = _money(data["credit_limit"])
        if limit != c.credit_limit:
            actor.require(CREDIT_PERMISSION)
            c.credit_limit = limit
    after = c.safe_fields()
    if after != before:
        _event(session, "customer.updated", c)
        old, new = changes(before, after)
        audit(session, actor, "customer.updated", "customer", c.id, before=old, after=new)
    await session.commit()
    return c


async def set_customer_active(
    session: AsyncSession, actor: CurrentUser, customer_id: UUID, active: bool, reason: str | None
) -> Customer:
    """A deactivated customer keeps the ledger; no new credit sales."""
    c = await get_customer(session, customer_id, lock=True)
    if c.is_active != active:
        c.is_active = active
        action = "customer.activated" if active else "customer.deactivated"
        _event(session, action, c)
        audit(session, actor, action, "customer", c.id, before={"is_active": not active},
              after={"is_active": active, **({"reason": reason} if reason else {})})  # fmt: skip
        await session.commit()
    return c
