"""Controlled-drug register commands.

    python -m controlled_service.cli open-balances   # once after installing S5
    python -m controlled_service.cli check           # what the 00:20 job does, now

open-balances: controlled stock that existed before the register started gets an
"opening" entry per batch (only batches with no register entry yet), so the
register equals stock. Run it when no controlled sales are going on.
"""

import argparse
import asyncio
import json
import sys

from .db import db
from .services.clients import get_clients
from .services.reconcile import reconcile
from .services.register import open_balances


async def _run(command: str) -> object:
    try:
        async with db.sessionmaker() as session:
            if command == "open-balances":
                return await open_balances(session, get_clients())
            return await reconcile(session, get_clients())
    finally:
        await db.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="controlled_service.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("open-balances", help="opening entries for controlled stock that has no register entry")
    sub.add_parser("check", help="verify the chains and compare the register with stock")
    args = parser.parse_args(argv)
    result = asyncio.run(_run(args.command))
    if result is None:
        print("Another replica is running the check; nothing done.")
        return 1
    print(json.dumps(result) if isinstance(result, dict) else f"{result} opening entries written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
