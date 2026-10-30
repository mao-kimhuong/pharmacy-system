"""Events the purchasing service listens to (RabbitMQ queue `purchasing.events`).

- branch.*    → local copy of branches (codes for PO / receipt numbers)
- medicine.*  → local copy of medicines and pack units (PO lines); older versions ignored
- transfer.*  → progress of purchase requests filled by a transfer
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import copies

from ..models import KnownBranch, Product, ProductPackUnit
from . import requests

ROUTING_KEYS = ("branch.*", "medicine.*", "transfer.*")


async def handle_event(
    session: AsyncSession, event_type: str, payload: dict[str, Any], message_id: UUID
) -> None:
    if event_type in copies.BRANCH_EVENTS:
        await copies.upsert_branch(session, KnownBranch, payload)
    elif event_type in copies.MEDICINE_EVENTS:
        await copies.upsert_product(session, Product, ProductPackUnit, payload)
    elif event_type.startswith("transfer.") and payload.get("transfer_id"):
        await requests.on_transfer(session, event_type, payload)
