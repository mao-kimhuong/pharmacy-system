"""Sales admin commands.

python -m sales_service.cli recover     # finish sales/returns left half-way (what the task does every minute)
python -m sales_service.cli republish   # commission lines and periods as events again (make resync)
"""

import argparse
import asyncio
import json
import sys

from .config import get_settings
from .db import db
from .services.clients import get_clients
from .services.recovery import recover


async def _recover() -> dict:
    try:
        return await recover(db, get_clients(), get_settings().pending_timeout_seconds)
    finally:
        await db.dispose()


async def _republish() -> int:
    from .services.commission import republish

    try:
        async with db.sessionmaker() as session:
            return await republish(session)
    finally:
        await db.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sales_service.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("recover", help="compensate / finish sagas left pending")
    sub.add_parser("republish", help="send commission lines and periods as events again")
    args = parser.parse_args(argv)
    if args.command == "recover":
        print(json.dumps(asyncio.run(_recover())))
    elif args.command == "republish":
        print(f"{asyncio.run(_republish())} commission lines republished")
    return 0


if __name__ == "__main__":
    sys.exit(main())
