"""Sales admin commands.

python -m sales_service.cli recover   # finish sales/returns left half-way (what the task does every minute)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sales_service.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("recover", help="compensate / finish sagas left pending")
    args = parser.parse_args(argv)
    if args.command == "recover":
        print(json.dumps(asyncio.run(_recover())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
