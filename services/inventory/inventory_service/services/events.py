"""Events the inventory service listens to (RabbitMQ queue `inventory.events`).

- branch.*        → local copy of branches
- medicine.*      → local copy of medicines and pack units (older versions ignored)
- supplier.*      → local copy of suppliers (quick stock-in, batch identity)
- goods.received  → each receipt line becomes a batch (reused when medicine,
                    lot, expiry, supplier and cost are identical) + an "in"
                    movement at the receiving branch, booked once per line.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import copies

from ..models import KnownBranch, KnownSupplier, Product, ProductPackUnit
from .movements import already_booked, apply_movement, get_or_create_batch

ROUTING_KEYS = ("branch.*", "medicine.*", "supplier.*", "goods.received")
SUPPLIER_EVENTS = frozenset(
    {"supplier.created", "supplier.updated", "supplier.activated", "supplier.deactivated"}
)


async def handle_event(
    session: AsyncSession, event_type: str, payload: dict[str, Any], message_id: UUID
) -> None:
    if event_type in copies.BRANCH_EVENTS:
        await copies.upsert_branch(session, KnownBranch, payload)
    elif event_type in copies.MEDICINE_EVENTS:
        await copies.upsert_product(session, Product, ProductPackUnit, payload)
    elif event_type in SUPPLIER_EVENTS:
        values = {"id": UUID(payload["supplier_id"]), "code": payload["code"], "name": payload["name"],
                  "is_active": bool(payload["is_active"])}  # fmt: skip
        await session.execute(
            insert(KnownSupplier).values(**values)
            .on_conflict_do_update(index_elements=[KnownSupplier.id], set_={k: v for k, v in values.items() if k != "id"})
        )  # fmt: skip
    elif event_type == "goods.received":
        await book_goods_received(session, payload)


async def book_goods_received(session: AsyncSession, payload: dict[str, Any]) -> int:
    """Returns how many lines were booked (0 when all were booked before)."""
    branch_id = UUID(payload["branch_id"])
    supplier_id = UUID(payload["supplier_id"])
    received_at = datetime.fromisoformat(payload["received_at"])
    actor = UUID(payload["received_by"]) if payload.get("received_by") else None
    booked = 0
    for line in payload["lines"]:
        ref_id = str(line["receipt_line_id"])
        if await already_booked(session, "in", "receipt_line", ref_id):
            continue
        batch = await get_or_create_batch(
            session, medicine_id=UUID(line["medicine_id"]), lot_no=line["lot_no"],
            expiry_date=date.fromisoformat(line["expiry_date"]), supplier_id=supplier_id,
            cost_per_base=Decimal(line["cost_per_base"]), received_at=received_at,
        )  # fmt: skip
        await apply_movement(
            session, branch_id=branch_id, batch=batch, type="in", qty_base=int(line["qty_base"]),
            ref_type="receipt_line", ref_id=ref_id, reason=f"PO receipt {payload['number']}", actor_id=actor,
        )  # fmt: skip
        booked += 1
    return booked
