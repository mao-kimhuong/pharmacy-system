"""Events the sales service listens to (queue `sales.events`).

- branch.*                → local copy of branches (codes for invoice numbers)
- branch.settings_updated → receipt header / footer, opened-pack returns
- medicine.*              → products, pack units and sell prices (older versions ignored)
- customer.*              → customers (credit sales, names on invoices)
"""

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import copies

from ..models import BranchSettingsCopy, KnownBranch, KnownCustomer, Product, ProductPackUnit

ROUTING_KEYS = ("branch.*", "medicine.*", "customer.*")
CUSTOMER_EVENTS = frozenset(
    {"customer.created", "customer.updated", "customer.activated", "customer.deactivated"}
)


async def _upsert(session: AsyncSession, model: type, key: str, values: dict[str, Any]) -> None:
    await session.execute(insert(model).values(**values).on_conflict_do_update(
        index_elements=[getattr(model, key)], set_={k: v for k, v in values.items() if k != key}))  # fmt: skip


async def handle_event(
    session: AsyncSession, event_type: str, payload: dict[str, Any], message_id: UUID
) -> None:
    if event_type in copies.BRANCH_EVENTS:
        await copies.upsert_branch(session, KnownBranch, payload)
    elif event_type == "branch.settings_updated":
        await _upsert(session, BranchSettingsCopy, "branch_id", {
            "branch_id": UUID(payload["branch_id"]), "receipt_header": payload.get("receipt_header") or "",
            "receipt_footer": payload.get("receipt_footer") or "",
            "allow_opened_pack_returns": bool(payload.get("allow_opened_pack_returns", False))})  # fmt: skip
    elif event_type in copies.MEDICINE_EVENTS:
        await copies.upsert_product(session, Product, ProductPackUnit, payload)
    elif event_type in CUSTOMER_EVENTS:
        await _upsert(session, KnownCustomer, "id", {
            "id": UUID(payload["customer_id"]), "phone": payload["phone"], "name": payload["name"],
            "name_km": payload.get("name_km") or "", "credit_limit": Decimal(str(payload.get("credit_limit") or 0)),
            "is_active": bool(payload["is_active"])})  # fmt: skip
