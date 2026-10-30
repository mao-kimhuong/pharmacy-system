"""Customers admin commands.

    python -m customers_service.cli republish

republish: writes a customer.updated event (current state) for every customer to
the outbox. Use it when a service starts listening after customers already exist
(its queue did not exist yet, so it missed those events). Consumers store the
latest state, so running it twice is harmless.
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

from pharmacy_shared.outbox import add_event

from .db import db
from .models import Customer, OutboxEvent
from .services.customers import customer_payload


async def republish() -> int:
    async with db.sessionmaker() as session:
        count = 0
        for c in (await session.execute(select(Customer).order_by(Customer.created_at))).scalars():
            add_event(session, OutboxEvent, "customer.updated", customer_payload(c))
            count += 1
        await session.commit()
    await db.dispose()
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="customers_service.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("republish", help="re-send every customer as an event")
    parser.parse_args(argv)
    print(f"Queued {asyncio.run(republish())} customer events")
    return 0


if __name__ == "__main__":
    sys.exit(main())
