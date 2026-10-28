"""Events the customers service listens to (queue `customers.events`).

- branch.*          → local copy of branches (codes for payment numbers)
- invoice.created   → the number of a credit sale onto its debt (fallback when the
                      direct call from sales after the sale did not get through)
"""

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import copies

from ..models import CustomerAllocation, CustomerDebt, KnownBranch

ROUTING_KEYS = ("branch.*", "invoice.created")


async def handle_event(
    session: AsyncSession, event_type: str, payload: dict[str, Any], message_id: UUID
) -> None:
    if event_type in copies.BRANCH_EVENTS:
        await copies.upsert_branch(session, KnownBranch, payload)
    elif (
        event_type == "invoice.created"
        and payload.get("number")
        and Decimal(payload.get("credit_amount") or 0) > 0
    ):
        debt = (await session.execute(select(CustomerDebt).where(
            CustomerDebt.invoice_id == UUID(payload["invoice_id"])))).scalar_one_or_none()  # fmt: skip
        if debt is not None and debt.invoice_no != payload["number"]:
            debt.invoice_no = payload["number"]
            await session.execute(update(CustomerAllocation).where(CustomerAllocation.debt_id == debt.id)
                                  .values(invoice_no=payload["number"]))  # fmt: skip
