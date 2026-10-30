"""Events the prescription service listens to (queue `prescription.events`).

- branch.* / branch.settings_updated → branches, default Rx validity
- medicine.*  → medicines with active ingredients and drug classes (older versions ignored)
- customer.*  → customers (a patient may be linked to one)
- invoice.created / .cancelled / .returned → dispensed quantities (dispensing.apply_invoice)
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import copies

from ..models import BranchSettingsCopy, KnownBranch, KnownCustomer, Product
from . import dispensing

ROUTING_KEYS = ("branch.*", "medicine.*", "customer.*", "invoice.*")
CUSTOMER_EVENTS = frozenset(
    {"customer.created", "customer.updated", "customer.activated", "customer.deactivated"}
)
INVOICE_EVENTS = frozenset({"invoice.created", "invoice.cancelled", "invoice.returned"})


async def _upsert(session: AsyncSession, model: type, key: str, values: dict[str, Any]) -> None:
    await session.execute(insert(model).values(**values).on_conflict_do_update(
        index_elements=[getattr(model, key)], set_={k: v for k, v in values.items() if k != key}))  # fmt: skip


async def upsert_product(session: AsyncSession, payload: dict[str, Any]) -> bool:
    product_id = UUID(str(payload["medicine_id"]))
    stored = (
        await session.execute(select(Product.version).where(Product.id == product_id).with_for_update())
    ).scalar_one_or_none()
    if stored is not None and stored >= int(payload["version"]):
        return False
    await _upsert(session, Product, "id", {
        "id": product_id, "version": int(payload["version"]), "sku": payload["sku"],
        "brand_name": payload["brand_name"], "generic_name": payload["generic_name"],
        "strength": payload.get("strength") or "", "dosage_form": payload.get("dosage_form") or "",
        "name_km": payload.get("name_km") or "", "base_unit": payload["base_unit"],
        "is_rx_only": bool(payload["is_rx_only"]), "controlled_schedule": payload.get("controlled_schedule"),
        "is_active": bool(payload["is_active"]),
        "active_ingredients": list(payload.get("active_ingredients") or []),
        "drug_classes": list(payload.get("drug_classes") or []),
    })  # fmt: skip
    return True


async def handle_event(
    session: AsyncSession, event_type: str, payload: dict[str, Any], message_id: UUID
) -> None:
    if event_type in copies.BRANCH_EVENTS:
        await copies.upsert_branch(session, KnownBranch, payload)
    elif event_type == "branch.settings_updated":
        await _upsert(session, BranchSettingsCopy, "branch_id", {
            "branch_id": UUID(payload["branch_id"]), "rx_valid_days": int(payload.get("rx_valid_days") or 30)})  # fmt: skip
    elif event_type in copies.MEDICINE_EVENTS:
        await upsert_product(session, payload)
    elif event_type in CUSTOMER_EVENTS:
        await _upsert(session, KnownCustomer, "id", {
            "id": UUID(payload["customer_id"]), "name": payload["name"], "phone": payload["phone"],
            "is_active": bool(payload["is_active"])})  # fmt: skip
    elif event_type in INVOICE_EVENTS:
        await dispensing.apply_invoice(session, event_type, payload)
