"""Events the document service listens to (RabbitMQ queue `document.events`).

- medicine.*        → local copy of products and pack units, used to print labels.
- purchase_order.*  → local copy of purchase orders, used to print the PO PDF.
- invoice.*         → local copy of invoices, used to print receipts and A4 invoices.
  Each event carries the whole product with a `version`; an event older than
  the stored copy (delivered out of order) is ignored.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import copies
from pharmacy_shared.copies import MEDICINE_EVENTS

from ..models import Product, ProductPackUnit
from . import purchase_orders, receipts

ROUTING_KEYS = ("medicine.*", "purchase_order.*", "invoice.*")


async def handle_event(
    session: AsyncSession, event_type: str, payload: dict[str, Any], message_id: UUID
) -> None:
    if event_type in MEDICINE_EVENTS:
        await upsert_product(session, payload)
    elif event_type in purchase_orders.PO_EVENTS:
        await purchase_orders.upsert_po(session, payload)
    elif event_type in receipts.INVOICE_EVENTS:
        await receipts.upsert_invoice(session, payload)


async def upsert_product(session: AsyncSession, payload: dict[str, Any]) -> bool:
    """Returns False when the stored copy is already as new or newer."""
    return await copies.upsert_product(session, Product, ProductPackUnit, payload)
