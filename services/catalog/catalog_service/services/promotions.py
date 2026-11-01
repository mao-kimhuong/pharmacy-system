"""Promotions: the rules live here (catalog.promotions); sales keeps a copy from
promotion.* events and applies them at the till. Rules:

- Code unique; type percent_off / amount_off / buy_x_get_y / bundle_price /
  qty_tiers / group_price, each with the fields it needs (checked here).
- Targets: medicines, categories or brands (at least one), except bundle_price
  (its bundle items) – targets must exist.
- Limits: from / to (date-time), days of week (0 = Monday), branches, customer
  groups (group_price needs at least one), max uses in total / per customer.
- stackable (may combine with other stackable ones) or exclusive; Rx-only and
  controlled medicines are left out unless include_rx.
- Never deleted: deactivate / activate. Every change: promotion.* event with the
  whole rule and its version, and a User Log entry.
"""

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.audit import changes, record_audit
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.internal import InternalClient
from pharmacy_shared.outbox import add_event

from ..models import Brand, Category, Medicine, OutboxEvent, Promotion
from .common import SERVICE, clean, commit

FIELDS = ("name", "name_km", "type", "value", "buy_qty", "get_qty", "tiers", "bundle_items", "medicine_ids",
          "category_ids", "brand_ids", "starts_at", "ends_at", "days_of_week", "branch_ids", "customer_group_ids",
          "max_uses_total", "max_uses_per_customer", "stackable", "include_rx")  # fmt: skip


def _bad(message: str, field: str) -> AppError:
    return AppError(ErrorCode.VALIDATION_ERROR, message, status_code=422, details={"field": field})


def payload(p: Promotion) -> dict[str, Any]:
    return {
        "promotion_id": str(p.id), "version": p.version, "code": p.code, "name": p.name, "name_km": p.name_km,
        "type": p.type, "value": str(p.value) if p.value is not None else None, "buy_qty": p.buy_qty,
        "get_qty": p.get_qty, "tiers": p.tiers, "bundle_items": p.bundle_items, "medicine_ids": p.medicine_ids,
        "category_ids": p.category_ids, "brand_ids": p.brand_ids,
        "starts_at": p.starts_at.isoformat() if p.starts_at else None,
        "ends_at": p.ends_at.isoformat() if p.ends_at else None, "days_of_week": p.days_of_week,
        "branch_ids": p.branch_ids, "customer_group_ids": p.customer_group_ids, "max_uses_total": p.max_uses_total,
        "max_uses_per_customer": p.max_uses_per_customer, "stackable": p.stackable, "include_rx": p.include_rx,
        "is_active": p.is_active,
    }  # fmt: skip


def _summary(p: Promotion) -> dict[str, Any]:
    return {k: (str(v) if isinstance(v, (Decimal, UUID)) else v.isoformat() if hasattr(v, "isoformat") else v)
            for k, v in ((f, getattr(p, f)) for f in (*FIELDS, "is_active"))}  # fmt: skip


async def _exist(session: AsyncSession, model: type, ids: list[str], field: str) -> list[str]:
    ids = sorted({str(i) for i in ids})
    if ids:
        found = (await session.execute(select(func.count()).select_from(model).where(
            model.id.in_([UUID(i) for i in ids])))).scalar_one()  # fmt: skip
        if found != len(ids):
            raise _bad(f"Unknown id in {field}", field)
    return ids


async def _check(session: AsyncSession, p: Promotion) -> None:
    t = p.type
    if t in ("percent_off",) and not (p.value and Decimal("0") < p.value <= Decimal("100")):
        raise _bad("A percentage between 0 and 100", "value")
    if t in ("amount_off", "bundle_price", "group_price") and not (p.value is not None and p.value >= 0):
        raise _bad("An amount in USD", "value")
    if t == "buy_x_get_y" and not (p.buy_qty and p.get_qty and p.buy_qty > 0 and p.get_qty > 0):
        raise _bad("buy_qty and get_qty (base units)", "buy_qty")
    if t == "qty_tiers":
        tiers = sorted(p.tiers or [], key=lambda x: x["min_qty"])
        if not tiers or any(not (0 < Decimal(str(x["percent"])) <= 100) or x["min_qty"] < 1 for x in tiers):
            raise _bad("Tiers: min_qty ≥ 1 and percent between 0 and 100", "tiers")
        p.tiers = [{"min_qty": int(x["min_qty"]), "percent": str(x["percent"])} for x in tiers]
    if t == "bundle_price":
        items = p.bundle_items or []
        if len(items) < 1 or sum(int(x["qty_base"]) for x in items) < 2:
            raise _bad("A bundle has at least two units", "bundle_items")
        await _exist(session, Medicine, [x["medicine_id"] for x in items], "bundle_items")
        p.bundle_items = [
            {"medicine_id": str(x["medicine_id"]), "qty_base": int(x["qty_base"])} for x in items
        ]
    elif not (p.medicine_ids or p.category_ids or p.brand_ids):
        raise _bad("Choose the medicines, categories or brands it applies to", "medicine_ids")
    if t == "group_price" and not p.customer_group_ids:
        raise _bad("A group price needs the customer groups", "customer_group_ids")
    if p.starts_at and p.ends_at and p.ends_at <= p.starts_at:
        raise _bad("ends_at is before starts_at", "ends_at")
    p.medicine_ids = await _exist(session, Medicine, p.medicine_ids or [], "medicine_ids")
    p.category_ids = await _exist(session, Category, p.category_ids or [], "category_ids")
    p.brand_ids = await _exist(session, Brand, p.brand_ids or [], "brand_ids")
    p.branch_ids = sorted({str(b) for b in p.branch_ids or []})
    p.customer_group_ids = sorted({str(g) for g in p.customer_group_ids or []})
    p.days_of_week = sorted(set(p.days_of_week or []))


def _publish(
    session: AsyncSession, actor: CurrentUser, p: Promotion, event: str, before: dict | None
) -> None:
    add_event(session, OutboxEvent, event, payload(p))
    old, new = changes(before, _summary(p)) if before else ({}, _summary(p))
    record_audit(session, OutboxEvent, service=SERVICE, action=event, entity_type="promotion", entity_id=p.id,
                 actor=actor, before=old, after={"code": p.code, **new})  # fmt: skip


async def get(session: AsyncSession, promotion_id: UUID, *, lock: bool = False) -> Promotion:
    query = select(Promotion).where(Promotion.id == promotion_id)
    p = (await session.execute(query.with_for_update() if lock else query)).scalar_one_or_none()
    if p is None:
        raise AppError(ErrorCode.NOT_FOUND, "Promotion not found", status_code=404)
    return p


async def list_promotions(session: AsyncSession, active: bool | None) -> list[Promotion]:
    query = select(Promotion)
    if active is not None:
        query = query.where(Promotion.is_active.is_(active))
    return list((await session.execute(query.order_by(Promotion.code))).scalars())


async def create(session: AsyncSession, actor: CurrentUser, data: dict[str, Any]) -> Promotion:
    code = clean(data["code"]).upper()
    if (await session.execute(select(Promotion.id).where(Promotion.code == code))).first():
        raise AppError(ErrorCode.DUPLICATE_CODE, f"Promotion code {code} is already used", status_code=409)
    p = Promotion(code=code, version=1, is_active=True, created_by=actor.id,
                  **{f: data.get(f) for f in FIELDS if f in data})  # fmt: skip
    p.name, p.name_km = clean(p.name), clean(p.name_km)
    await _check(session, p)
    session.add(p)
    await session.flush()
    _publish(session, actor, p, "promotion.created", None)
    await commit(session)
    return p


async def update(
    session: AsyncSession, actor: CurrentUser, promotion_id: UUID, data: dict[str, Any]
) -> Promotion:
    p = await get(session, promotion_id, lock=True)
    before = _summary(p)
    for f in FIELDS:
        if f in data and f != "type":
            setattr(p, f, data[f])
    await _check(session, p)
    if _summary(p) != before:
        p.version += 1
        _publish(session, actor, p, "promotion.updated", before)
    await commit(session)
    return p


async def set_active(
    session: AsyncSession, actor: CurrentUser, promotion_id: UUID, active: bool
) -> Promotion:
    p = await get(session, promotion_id, lock=True)
    if p.is_active != active:
        before = _summary(p)
        p.is_active, p.version = active, p.version + 1
        _publish(session, actor, p, "promotion.activated" if active else "promotion.deactivated", before)
        await commit(session)
    return p


async def republish(session: AsyncSession) -> int:
    rows = list((await session.execute(select(Promotion))).scalars())
    for p in rows:
        add_event(session, OutboxEvent, "promotion.updated", {**payload(p), "resync": True})
    return len(rows)


async def preview(session: AsyncSession, actor: CurrentUser, sales: InternalClient, data: dict[str, Any],
                  cart: dict[str, Any]) -> dict[str, Any]:  # fmt: skip
    """A draft promotion (checked like create, never saved) on a sample cart: the sales
    service prices it with the active promotions (same pricing as the till) and says
    which promotions compete on each line and which one wins."""
    from uuid import uuid4

    p = Promotion(id=uuid4(), code=clean(data["code"]).upper(), version=0, is_active=True,
                  **{f: data.get(f) for f in FIELDS if f in data})  # fmt: skip
    p.name, p.name_km = clean(p.name), clean(p.name_km)
    await _check(session, p)
    draft = payload(p)
    await session.rollback()  # nothing is kept
    actor.require_branch(UUID(str(cart["branch_id"])))
    return await sales.post("/carts/preview", {"cart": cart, "draft_promotion": draft}, actor=actor,
                            branch_id=cart["branch_id"])  # fmt: skip
