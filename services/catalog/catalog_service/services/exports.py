"""Product export in the import layout, so an exported file can be edited and
imported again. Text cells are formula-escaped (see spreadsheet.write_workbook)."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Medicine
from .spreadsheet import KEYS, write_workbook


def _row(m: Medicine, pack) -> list:
    values = {
        "sku": m.sku,
        "brand_name": m.brand_name,
        "generic_name": m.generic_name,
        "strength": m.strength,
        "dosage_form": m.dosage_form,
        "name_km": m.name_km,
        "category": m.category.name_en if m.category else "",
        "brand": m.brand.name_en if m.brand else "",
        "manufacturer": m.manufacturer,
        "base_unit": m.base_unit,
        "rx_only": "yes" if m.is_rx_only else "no",
        "controlled_schedule": m.controlled_schedule or "",
        "storage": m.storage,
        "reorder_level": m.reorder_level,
        "active_ingredients": "; ".join(m.active_ingredients or []),
        "drug_classes": "; ".join(m.drug_classes or []),
        "pack_unit": pack.name,
        "qty_in_base": pack.qty_in_base,
        "barcode": pack.barcode or "",
        "sell_price_usd": f"{pack.sell_price:.2f}",
    }
    return [values[k] for k in KEYS]


async def export_products(session: AsyncSession, include_inactive: bool) -> bytes:
    query = select(Medicine).order_by(func.lower(Medicine.brand_name), Medicine.sku)
    if not include_inactive:
        query = query.where(Medicine.is_active.is_(True))
    rows = [
        _row(m, p)
        for m in (await session.execute(query)).scalars()
        for p in sorted(m.pack_units, key=lambda p: (p.qty_in_base, p.name))
        if p.is_active or include_inactive
    ]
    return write_workbook([("Products", list(KEYS), rows)])
