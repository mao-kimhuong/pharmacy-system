"""Catalog admin commands.

    python -m catalog_service.cli republish
    python -m catalog_service.cli price-history   # fill the price history once from the event history

republish: writes a medicine.updated event (current state, current version) for
every medicine, and category.updated / brand.updated for every category and
brand, and promotion.updated for every promotion, to the outbox. Use it when a service starts listening after products
already exist (its queue did not exist yet, so it missed those events).
Consumers ignore versions they already have, so running it twice is harmless.
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

from pharmacy_shared.outbox import add_event

from .db import db
from .models import Brand, Category, Medicine, OutboxEvent
from .services import lookups, medicines, promotions


async def republish() -> tuple[int, int]:
    async with db.sessionmaker() as session:
        lookup_count = 0
        for model in (Category, Brand):
            for row in (await session.execute(select(model))).scalars():
                add_event(
                    session, OutboxEvent, f"{lookups.kind_of(model)}.updated", lookups.event_payload(row)
                )
                lookup_count += 1
        count = 0
        for m in (await session.execute(select(Medicine).order_by(Medicine.sku))).scalars():
            # resync: copies refresh even when they have this version (new fields in a later sprint)
            add_event(
                session, OutboxEvent, "medicine.updated", {**medicines.event_payload(m), "resync": True}
            )
            count += 1
        lookup_count += await promotions.republish(session)
        await session.commit()
    await db.dispose()
    return count, lookup_count


async def _price_history() -> int:
    from .services.prices import backfill

    try:
        async with db.sessionmaker() as session:
            return await backfill(session)
    finally:
        await db.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="catalog_service.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("republish", help="re-send every medicine, category and brand as events")
    sub.add_parser("price-history", help="fill the price history from the event history (once; safe to repeat)")
    args = parser.parse_args(argv)
    if args.command == "republish":
        count, lookup_count = asyncio.run(republish())
        print(f"Queued {count} medicine and {lookup_count} category/brand events")
    elif args.command == "price-history":
        print(f"{asyncio.run(_price_history())} price history rows from the event history")
    return 0


if __name__ == "__main__":
    sys.exit(main())
