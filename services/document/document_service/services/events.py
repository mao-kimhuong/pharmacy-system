"""Events the document service listens to (RabbitMQ queue `document.events`).

- medicine.*  → local copy of products and pack units, used to print labels.
  Each event carries the whole product with a `version`; an event older than
  the stored copy (delivered out of order) is ignored.
"""

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Product, ProductPackUnit

ROUTING_KEYS = ("medicine.*",)
MEDICINE_EVENTS = frozenset(
    {"medicine.created", "medicine.updated", "medicine.activated", "medicine.deactivated"}
)


async def handle_event(
    session: AsyncSession, event_type: str, payload: dict[str, Any], message_id: UUID
) -> None:
    if event_type in MEDICINE_EVENTS:
        await upsert_product(session, payload)


async def upsert_product(session: AsyncSession, payload: dict[str, Any]) -> bool:
    """Returns False when the stored copy is already as new or newer."""
    product_id = UUID(str(payload["medicine_id"]))
    version = int(payload["version"])
    stored = (
        await session.execute(select(Product.version).where(Product.id == product_id).with_for_update())
    ).scalar_one_or_none()
    if stored is not None and stored >= version:
        return False
    values = {
        "id": product_id,
        "version": version,
        "sku": str(payload["sku"]),
        "brand_name": str(payload["brand_name"]),
        "generic_name": str(payload["generic_name"]),
        "strength": str(payload.get("strength") or ""),
        "dosage_form": str(payload.get("dosage_form") or ""),
        "name_km": str(payload.get("name_km") or ""),
        "base_unit": str(payload["base_unit"]),
        "is_rx_only": bool(payload["is_rx_only"]),
        "controlled_schedule": payload.get("controlled_schedule"),
        "is_active": bool(payload["is_active"]),
    }
    await session.execute(
        insert(Product)
        .values(**values)
        .on_conflict_do_update(
            index_elements=[Product.id], set_={k: v for k, v in values.items() if k != "id"}
        )
    )
    for pack in payload.get("pack_units") or []:
        pack_values = {
            "id": UUID(str(pack["id"])),
            "product_id": product_id,
            "name": str(pack["name"]),
            "qty_in_base": int(pack["qty_in_base"]),
            "barcode": pack.get("barcode") or None,
            "sell_price": Decimal(str(pack["sell_price"])),
            "is_base": bool(pack["is_base"]),
            "is_active": bool(pack["is_active"]),
        }
        await session.execute(
            insert(ProductPackUnit)
            .values(**pack_values)
            .on_conflict_do_update(
                index_elements=[ProductPackUnit.id], set_={k: v for k, v in pack_values.items() if k != "id"}
            )
        )
    return True
