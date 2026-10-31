"""Hampers (kits). Rules:

- A hamper is a medicine of kind "hamper": its own SKU, name, price and barcode
  (one pack unit, the hamper), made of fixed components (active, ordinary
  medicines, base units). It has no stock or batches of its own: selling one
  takes its components from stock (FEFO) and only they appear in stock takes,
  purchase orders, receiving and transfers.
- Rx-only when any component is Rx-only (kept up to date when a component
  changes); a controlled medicine cannot be in a hamper.
- catalog.hampers. Changing the contents bumps the version (medicine.updated).
  A component of an active hamper cannot be deactivated.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode

from ..models import Brand, Category, HamperComponent, Medicine, PackUnit
from .common import clean, clean_sku, commit
from .medicines import _lookup, check_barcode_free, check_sku_free, get_medicine, price, record_change


async def _components(session: AsyncSession, raw: list[dict[str, Any]]) -> list[tuple[Medicine, int]]:
    out, seen = [], set()
    for i, x in enumerate(raw, start=1):
        m = await session.get(Medicine, x["medicine_id"])
        if m is None or not m.is_active or m.kind != "medicine":
            raise AppError(ErrorCode.UNKNOWN_MEDICINE, f"Component {i}: unknown, inactive or itself a hamper",
                           status_code=422, details={"component": i})  # fmt: skip
        if m.controlled_schedule:
            raise AppError(ErrorCode.VALIDATION_ERROR, f"Component {i}: {m.sku} is controlled and cannot be in a hamper",
                           status_code=422, details={"component": i})  # fmt: skip
        if m.id in seen:
            raise AppError(
                ErrorCode.VALIDATION_ERROR, f"Component {i}: {m.sku} is listed twice", status_code=422
            )
        seen.add(m.id)
        out.append((m, int(x["qty_base"])))
    if len(out) < 2 and sum(q for _, q in out) < 2:
        raise AppError(ErrorCode.VALIDATION_ERROR, "A hamper has at least two units", status_code=422)
    return out


def _apply(h: Medicine, parts: list[tuple[Medicine, int]]) -> None:
    h.components.clear()
    for i, (m, qty) in enumerate(parts, start=1):
        h.components.append(HamperComponent(component_id=m.id, line_no=i, qty_base=qty))
    h.is_rx_only = any(m.is_rx_only for m, _ in parts)


async def create_hamper(session: AsyncSession, actor: CurrentUser, data: dict[str, Any]) -> Medicine:
    sku = clean_sku(data["sku"])
    await check_sku_free(session, sku)
    barcode = clean(data.get("barcode")) or None
    await check_barcode_free(session, barcode)
    parts = await _components(session, data["components"])
    h = Medicine(sku=sku, brand_name=clean(data["name"]), generic_name="Hamper", name_km=clean(data.get("name_km")),
                 strength="", dosage_form="kit", manufacturer="", base_unit="hamper", kind="hamper",
                 storage="cold" if any(m.storage == "cold" for m, _ in parts) else "room", reorder_level=0,
                 active_ingredients=[], drug_classes=[], is_rx_only=False, version=0, created_by=actor.id,
                 pack_units=[PackUnit(name="hamper", qty_in_base=1, barcode=barcode, sell_price=price(data["price"]),
                                      is_base=True)], components=[])  # fmt: skip
    h.category = await _lookup(session, Category, data.get("category_id"))
    h.brand = await _lookup(session, Brand, data.get("brand_id"))
    session.add(h)
    await session.flush()
    _apply(h, parts)
    await session.flush()
    record_change(session, actor, h, "hamper.created", {}, event="medicine.created")
    await commit(session)
    return await get_medicine(session, h.id)


async def set_components(
    session: AsyncSession, actor: CurrentUser, hamper_id: UUID, raw: list[dict[str, Any]]
) -> Medicine:
    h = await get_medicine(session, hamper_id, lock=True)
    if h.kind != "hamper":
        raise AppError(ErrorCode.NOT_FOUND, "Hamper not found", status_code=404)
    before = h.safe_fields()
    _apply(h, await _components(session, raw))
    await session.flush()
    record_change(session, actor, h, "hamper.updated", before)
    await commit(session)
    return await get_medicine(session, h.id)


async def hampers_using(session: AsyncSession, medicine_id: UUID) -> list[Medicine]:
    ids = select(HamperComponent.hamper_id).where(HamperComponent.component_id == medicine_id)
    return list((await session.execute(select(Medicine).where(Medicine.id.in_(ids)))).scalars())


async def refresh_hampers_of(session: AsyncSession, actor: CurrentUser, m: Medicine) -> None:
    """A component became (or stopped being) Rx-only: its hampers follow."""
    if m.kind != "medicine":
        return
    for h in await hampers_using(session, m.id):
        before = h.safe_fields()
        parts = [(await session.get(Medicine, c.component_id), c.qty_base) for c in h.components]
        rx = any(p.is_rx_only for p, _ in parts)
        if rx != h.is_rx_only:
            h.is_rx_only = rx
            record_change(session, actor, h, "hamper.updated", before, extra={"because": m.sku})


async def list_hampers(session: AsyncSession) -> list[Medicine]:
    return list(
        (
            await session.execute(select(Medicine).where(Medicine.kind == "hamper").order_by(Medicine.sku))
        ).scalars()
    )
