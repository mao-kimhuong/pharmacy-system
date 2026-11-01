
"""Medicines and pack units. Rules:

- A controlled medicine (schedule I-IV) is always prescription-only.
- Exactly one base pack unit per medicine, qty_in_base = 1, named like base_unit;
  it is created with the medicine and cannot be deactivated. Other pack units
  hold 2 or more base units.
- Barcodes are unique across all pack units (active or not); SKUs are unique.
- Never deleted: deactivate (with a reason) / activate.
- Cost is not stored here (it is on batches in the inventory service).
- Every change: one medicine.* event with the full product (other services keep
  a copy) and one User Log entry with only the fields that changed.
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, or_, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from pharmacy_shared.audit import changes, record_audit
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.outbox import add_event

from ..models import Brand, Category, Medicine, OutboxEvent, PackUnit
from . import lookups
from .common import SERVICE, clean, clean_sku, commit, escape_like, not_found

CENT = Decimal("0.01")
_TEXT_FIELDS = ("brand_name", "generic_name", "strength", "dosage_form", "name_km", "manufacturer")
MAX_TERMS = 10


def terms(values: list[str] | None) -> list[str]:
    """Ingredients / drug classes: trimmed, NFC, no duplicates (ignoring case)."""
    out, seen = [], set()
    for value in values or []:
        term = clean(value)[:80]
        if term and term.casefold() not in seen:
            seen.add(term.casefold())
            out.append(term)
    return out[:MAX_TERMS]


def ingredients_from_generic(generic_name: str) -> list[str]:
    """ "Amoxicillin + Clavulanic acid" → ["Amoxicillin", "Clavulanic acid"]."""
    return terms(re.split(r"\s*\+\s*", generic_name or ""))


def price(value: Decimal | str | float) -> Decimal:
    return Decimal(str(value)).quantize(CENT)


# ---------------------------------------------------------------- events and audit


def _components(m: Medicine) -> list:
    """A medicine just made (not a hamper) has not loaded its components: none."""
    return [] if "components" in sa_inspect(m).unloaded else list(m.components)


def event_payload(m: Medicine) -> dict[str, Any]:
    """Everything other services need about a product (sales, inventory,
    prescription, document, reports). Prices are strings, in USD."""

    def ref(row: Category | Brand | None) -> dict[str, str] | None:
        return {"id": str(row.id), "name_en": row.name_en, "name_km": row.name_km} if row else None

    return {
        "medicine_id": str(m.id),
        "version": m.version,
        "sku": m.sku,
        "brand_name": m.brand_name,
        "generic_name": m.generic_name,
        "strength": m.strength,
        "dosage_form": m.dosage_form,
        "name_km": m.name_km,
        "category": ref(m.category),
        "brand": ref(m.brand),
        "manufacturer": m.manufacturer,
        "base_unit": m.base_unit,
        "is_rx_only": m.is_rx_only,
        "controlled_schedule": m.controlled_schedule,
        "storage": m.storage,
        "reorder_level": m.reorder_level,
        "active_ingredients": list(m.active_ingredients or []),
        "drug_classes": list(m.drug_classes or []),
        "is_active": m.is_active,
        "kind": m.kind,
        "components": [{"medicine_id": str(c.component_id), "qty_base": c.qty_base} for c in _components(m)],
        "pack_units": [
            {
                "id": str(p.id),
                "name": p.name,
                "qty_in_base": p.qty_in_base,
                "barcode": p.barcode,
                "sell_price": str(price(p.sell_price)),
                "is_base": p.is_base,
                "is_active": p.is_active,
            }
            for p in sorted(m.pack_units, key=lambda p: (p.qty_in_base, p.name))
        ],
    }


def record_change(
    session: AsyncSession,
    actor: CurrentUser,
    m: Medicine,
    action: str,
    before: dict[str, Any],
    *,
    event: str = "medicine.updated",
    extra: dict[str, Any] | None = None,
) -> bool:
    """Bump the version, queue the event and the User Log entry. Returns False
    (and records nothing) when nothing changed."""
    after = m.safe_fields()
    if before and before == after:
        return False
    m.version = (m.version or 0) + 1
    session.sync_session.info["actor_id"] = actor.id if actor else None  # who changed a price (price history)
    add_event(session, OutboxEvent, event, event_payload(m))
    old, new = changes(before, after) if before else ({}, after)
    record_audit(
        session,
        OutboxEvent,
        service=SERVICE,
        action=action,
        entity_type="medicine",
        entity_id=m.id,
        actor=actor,
        before=old,
        after={**new, **(extra or {})},
    )
    return True


# ---------------------------------------------------------------- checks


def apply_rx_rule(m: Medicine, explicit_rx: bool | None) -> None:
    """A controlled medicine is always Rx-only: asking for anything else is refused."""
    if explicit_rx is not None:
        m.is_rx_only = explicit_rx
    if m.controlled_schedule:
        if explicit_rx is False:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "A controlled medicine is always prescription-only",
                status_code=422,
                details={"field": "is_rx_only"},
            )
        m.is_rx_only = True


async def check_sku_free(session: AsyncSession, sku: str, exclude: UUID | None = None) -> None:
    found = (await session.execute(select(Medicine.id).where(Medicine.sku == sku))).scalar_one_or_none()
    if found is not None and found != exclude:
        raise AppError(ErrorCode.DUPLICATE_SKU, f"SKU {sku} is already used", status_code=409)


async def check_barcode_free(session: AsyncSession, barcode: str | None, exclude: UUID | None = None) -> None:
    if not barcode:
        return
    row = (
        await session.execute(
            select(PackUnit.id, Medicine.sku, PackUnit.name)
            .join(Medicine, Medicine.id == PackUnit.medicine_id)
            .where(PackUnit.barcode == barcode)
        )
    ).first()
    if row is not None and row.id != exclude:
        raise AppError(
            ErrorCode.DUPLICATE_BARCODE,
            f"Barcode {barcode} is already used by {row.sku} ({row.name})",
            status_code=409,
            details={"barcode": barcode, "sku": row.sku},
        )


def check_pack_name_free(m: Medicine, name: str, exclude: UUID | None = None) -> None:
    for p in m.pack_units:
        if p.name.lower() == name.lower() and p.id != exclude:
            raise AppError(
                ErrorCode.DUPLICATE_NAME, f"{m.sku} already has a pack unit named {p.name!r}", status_code=409
            )


async def _lookup(session: AsyncSession, model: type, row_id: UUID | None) -> Category | Brand | None:
    if row_id is None:
        return None
    row = await session.get(model, row_id)
    if row is None or not row.is_active:
        code = ErrorCode.UNKNOWN_CATEGORY if model is Category else ErrorCode.UNKNOWN_BRAND
        raise AppError(code, f"Unknown or inactive {lookups.kind_of(model)}", status_code=422)
    return row


# ---------------------------------------------------------------- reading


@dataclass(frozen=True)
class MedicineFilter:
    q: str | None = None
    category_id: UUID | None = None
    brand_id: UUID | None = None
    is_rx_only: bool | None = None
    controlled: bool | None = None
    include_inactive: bool = False


def _name_matches(term: str) -> ColumnElement[bool]:
    like = f"%{escape_like(term)}%"
    return or_(
        Medicine.brand_name.ilike(like, escape="\\"),
        Medicine.generic_name.ilike(like, escape="\\"),
        Medicine.name_km.ilike(like, escape="\\"),
    )


async def _page(session: AsyncSession, query, page: int, size: int, *order) -> tuple[list[Medicine], int]:
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = await session.execute(query.order_by(*order).offset((page - 1) * size).limit(size))
    return list(rows.scalars()), int(total)


async def list_medicines(
    session: AsyncSession, f: MedicineFilter, page: int, size: int
) -> tuple[list[Medicine], int]:
    query = select(Medicine)
    if f.q and clean(f.q):
        term = clean(f.q)
        query = query.where(
            or_(_name_matches(term), Medicine.sku.ilike(f"%{escape_like(term)}%", escape="\\"))
        )
    if f.category_id:
        query = query.where(Medicine.category_id == f.category_id)
    if f.brand_id:
        query = query.where(Medicine.brand_id == f.brand_id)
    if f.is_rx_only is not None:
        query = query.where(Medicine.is_rx_only.is_(f.is_rx_only))
    if f.controlled is not None:
        query = query.where(
            Medicine.controlled_schedule.is_not(None)
            if f.controlled
            else Medicine.controlled_schedule.is_(None)
        )
    if not f.include_inactive:
        query = query.where(Medicine.is_active.is_(True))
    return await _page(session, query, page, size, func.lower(Medicine.brand_name), Medicine.id)


async def search(
    session: AsyncSession, q: str, page: int, size: int
) -> tuple[list[tuple[Medicine, UUID | None]], int]:
    """POS / quick search over active products: an exact barcode first, then
    an exact SKU, then brand / generic / Khmer names (most similar first)."""
    term = clean(q)
    if not term:
        return [], 0
    scanned = select(PackUnit.medicine_id).where(PackUnit.barcode == term, PackUnit.is_active.is_(True))
    by_barcode = Medicine.id.in_(scanned)
    by_sku = Medicine.sku == term.upper()
    query = select(Medicine).where(Medicine.is_active.is_(True), or_(by_barcode, by_sku, _name_matches(term)))
    rank = case((by_barcode, 0), (by_sku, 1), else_=2)
    similarity = func.greatest(
        func.similarity(Medicine.brand_name, term),
        func.similarity(Medicine.generic_name, term),
        func.similarity(Medicine.name_km, term),
    )
    items, total = await _page(
        session, query, page, size, rank, similarity.desc(), func.lower(Medicine.brand_name), Medicine.id
    )
    hits = [(m, next((p.id for p in m.pack_units if p.barcode == term and p.is_active), None)) for m in items]
    return hits, total


async def get_medicine(session: AsyncSession, medicine_id: UUID, *, lock: bool = False) -> Medicine:
    query = select(Medicine).where(Medicine.id == medicine_id)
    if lock:
        query = query.with_for_update()
    m = (await session.execute(query)).scalar_one_or_none()
    if m is None:
        raise not_found("Medicine")
    return m


async def get_pack_unit(session: AsyncSession, pack_unit_id: UUID) -> tuple[Medicine, PackUnit]:
    medicine_id = (
        await session.execute(select(PackUnit.medicine_id).where(PackUnit.id == pack_unit_id))
    ).scalar_one_or_none()
    if medicine_id is None:
        raise not_found("Pack unit")
    m = await get_medicine(session, medicine_id, lock=True)  # pack unit changes lock the medicine
    return m, next(p for p in m.pack_units if p.id == pack_unit_id)


# ---------------------------------------------------------------- writing medicines


async def create_medicine(session: AsyncSession, actor: CurrentUser, data: dict[str, Any]) -> Medicine:
    sku = clean_sku(data["sku"])
    await check_sku_free(session, sku)
    base_unit = clean(data["base_unit"])
    m = Medicine(
        sku=sku,
        **{field: clean(data.get(field)) for field in _TEXT_FIELDS},
        base_unit=base_unit,
        controlled_schedule=data.get("controlled_schedule"),
        storage=data.get("storage") or "room",
        reorder_level=data.get("reorder_level") or 0,
        active_ingredients=terms(data.get("active_ingredients"))
        or ingredients_from_generic(data["generic_name"]),
        drug_classes=terms(data.get("drug_classes")),
        is_rx_only=False,
        version=0,
        created_by=actor.id,
        components=[],
    )
    m.category = await _lookup(session, Category, data.get("category_id"))
    m.brand = await _lookup(session, Brand, data.get("brand_id"))
    apply_rx_rule(m, data.get("is_rx_only"))
    m.pack_units = []

    packs = [{"name": base_unit, "qty_in_base": 1, "barcode": data.get("base_barcode"),
              "sell_price": data["base_price"], "is_base": True}]  # fmt: skip
    packs += [{**p, "is_base": False} for p in data.get("pack_units") or []]
    seen_barcodes: set[str] = set()
    for p in packs:
        name = clean(p["name"])
        check_pack_name_free(m, name)
        barcode = clean(p.get("barcode")) or None
        if barcode in seen_barcodes:
            raise AppError(ErrorCode.DUPLICATE_BARCODE, f"Barcode {barcode} is given twice", status_code=409)
        await check_barcode_free(session, barcode)
        if barcode:
            seen_barcodes.add(barcode)
        m.pack_units.append(
            PackUnit(name=name, qty_in_base=p["qty_in_base"], barcode=barcode,
                     sell_price=price(p["sell_price"]), is_base=p["is_base"])
        )  # fmt: skip
    session.add(m)
    await session.flush()
    record_change(session, actor, m, "medicine.created", {}, event="medicine.created")
    await commit(session)
    return m


async def update_medicine(
    session: AsyncSession, actor: CurrentUser, medicine_id: UUID, data: dict[str, Any]
) -> Medicine:
    m = await get_medicine(session, medicine_id, lock=True)
    before = m.safe_fields()
    if data.get("sku") is not None:
        sku = clean_sku(data["sku"])
        await check_sku_free(session, sku, m.id)
        m.sku = sku
    for field in _TEXT_FIELDS:
        if data.get(field) is not None:
            setattr(m, field, clean(data[field]))
    if "category_id" in data:
        m.category = await _lookup(session, Category, data["category_id"])
    if "brand_id" in data:
        m.brand = await _lookup(session, Brand, data["brand_id"])
    if data.get("base_unit") is not None:
        base_unit = clean(data["base_unit"])
        check_pack_name_free(m, base_unit, m.base_pack.id)
        m.base_unit = base_unit
        m.base_pack.name = base_unit  # the base pack unit is always named like the base unit
    if "controlled_schedule" in data:
        m.controlled_schedule = data["controlled_schedule"]
    if data.get("storage") is not None:
        m.storage = data["storage"]
    if data.get("reorder_level") is not None:
        m.reorder_level = data["reorder_level"]
    if data.get("active_ingredients") is not None:
        m.active_ingredients = terms(data["active_ingredients"]) or ingredients_from_generic(m.generic_name)
    if data.get("drug_classes") is not None:
        m.drug_classes = terms(data["drug_classes"])
    apply_rx_rule(m, data.get("is_rx_only"))
    if m.kind == "hamper" and m.controlled_schedule:
        raise AppError(
            ErrorCode.VALIDATION_ERROR, "A hamper cannot be a controlled medicine", status_code=422
        )
    record_change(session, actor, m, "medicine.updated", before)
    from .hampers import refresh_hampers_of  # hampers imports this module

    await refresh_hampers_of(session, actor, m)
    await commit(session)
    return m


async def set_medicine_active(
    session: AsyncSession, actor: CurrentUser, medicine_id: UUID, active: bool, reason: str | None
) -> Medicine:
    m = await get_medicine(session, medicine_id, lock=True)
    if m.is_active == active:
        return m
    if not active:
        from .hampers import hampers_using

        used = [h.sku for h in await hampers_using(session, m.id) if h.is_active]
        if used:
            raise AppError(ErrorCode.VALIDATION_ERROR, f"{m.sku} is in active hampers ({', '.join(used)}): "
                           "change or deactivate them first", status_code=409, details={"hampers": used})  # fmt: skip
    before = m.safe_fields()
    m.is_active = active
    action = "medicine.activated" if active else "medicine.deactivated"
    record_change(
        session, actor, m, action, before, event=action, extra={"reason": reason} if reason else None
    )
    await commit(session)
    return m


# ---------------------------------------------------------------- writing pack units


async def add_pack_unit(
    session: AsyncSession, actor: CurrentUser, medicine_id: UUID, data: dict[str, Any]
) -> PackUnit:
    m = await get_medicine(session, medicine_id, lock=True)
    if m.kind == "hamper":
        raise AppError(ErrorCode.VALIDATION_ERROR, "A hamper is sold as one unit: no other pack units",
                       status_code=422)  # fmt: skip
    before = m.safe_fields()
    name = clean(data["name"])
    check_pack_name_free(m, name)
    barcode = clean(data.get("barcode")) or None
    await check_barcode_free(session, barcode)
    pack = PackUnit(name=name, qty_in_base=data["qty_in_base"], barcode=barcode,
                    sell_price=price(data["sell_price"]), is_base=False)  # fmt: skip
    m.pack_units.append(pack)
    await session.flush()
    record_change(session, actor, m, "pack_unit.created", before)
    await commit(session)
    return pack


async def update_pack_unit(
    session: AsyncSession, actor: CurrentUser, pack_unit_id: UUID, data: dict[str, Any]
) -> PackUnit:
    m, pack = await get_pack_unit(session, pack_unit_id)
    before = m.safe_fields()
    if data.get("name") is not None:
        name = clean(data["name"])
        if pack.is_base:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "The base unit is renamed by changing the medicine's base_unit",
                status_code=422,
                details={"field": "name"},
            )
        check_pack_name_free(m, name, pack.id)
        pack.name = name
    if data.get("qty_in_base") is not None:
        if pack.is_base:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "The base unit always holds 1",
                status_code=422,
                details={"field": "qty_in_base"},
            )
        pack.qty_in_base = data["qty_in_base"]
    if "barcode" in data:
        barcode = clean(data["barcode"]) or None
        await check_barcode_free(session, barcode, pack.id)
        pack.barcode = barcode
    if data.get("sell_price") is not None:
        pack.sell_price = price(data["sell_price"])
    record_change(session, actor, m, "pack_unit.updated", before)
    await commit(session)
    return pack


async def set_pack_unit_active(
    session: AsyncSession, actor: CurrentUser, pack_unit_id: UUID, active: bool, reason: str | None
) -> PackUnit:
    m, pack = await get_pack_unit(session, pack_unit_id)
    if pack.is_active == active:
        return pack
    if pack.is_base and not active:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "The base unit cannot be deactivated; deactivate the medicine instead",
            status_code=422,
        )
    before = m.safe_fields()
    pack.is_active = active
    action = "pack_unit.activated" if active else "pack_unit.deactivated"
    extra = {"pack_unit": pack.name, **({"reason": reason} if reason else {})}
    record_change(session, actor, m, action, before, extra=extra)
    await commit(session)
    return pack
