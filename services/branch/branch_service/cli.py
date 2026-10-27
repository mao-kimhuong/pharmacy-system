"""Branch admin commands.

    python -m branch_service.cli republish

republish: writes a branch.updated event for every branch to the outbox. Use it
when a service starts listening after branches already exist.
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

from pharmacy_shared.outbox import add_event

from .db import db
from .models import Branch, OutboxEvent
from .services.branches import _event_payload


async def republish() -> int:
    async with db.sessionmaker() as session:
        count = 0
        for branch in (await session.execute(select(Branch).order_by(Branch.code))).scalars():
            add_event(session, OutboxEvent, "branch.updated", _event_payload(branch))
            count += 1
        await session.commit()
    await db.dispose()
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="branch_service.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("republish", help="re-send every branch as a branch.updated event")
    args = parser.parse_args(argv)
    if args.command == "republish":
        print(f"Queued {asyncio.run(republish())} branch events")
    return 0


if __name__ == "__main__":
    sys.exit(main())
