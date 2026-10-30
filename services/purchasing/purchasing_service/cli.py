"""Purchasing admin commands.

    python -m purchasing_service.cli republish

republish: writes a purchase_order.updated event (current state and version) for
every open purchase order (draft, sent, partially received), so a service that
started listening later (inventory's re-order list: quantities on order) has
them. Consumers ignore versions they already have; running it twice is harmless.
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

from pharmacy_shared.outbox import add_event

from .db import db
from .models import OutboxEvent, PurchaseOrder
from .services.orders import event_payload


async def republish() -> int:
    async with db.sessionmaker() as session:
        count = 0
        query = select(PurchaseOrder).where(PurchaseOrder.status.in_(("draft", "sent", "partially_received")))
        for po in (await session.execute(query.order_by(PurchaseOrder.created_at))).scalars():
            add_event(session, OutboxEvent, "purchase_order.updated", await event_payload(session, po))
            count += 1
        await session.commit()
    await db.dispose()
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="purchasing_service.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("republish", help="re-send every open purchase order as an event")
    parser.parse_args(argv)
    print(f"Queued {asyncio.run(republish())} purchase order events")
    return 0


if __name__ == "__main__":
    sys.exit(main())
