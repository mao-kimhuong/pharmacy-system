"""Inventory admin commands.

python -m inventory_service.cli expire-batches            # what the 00:05 job does, now
python -m inventory_service.cli expire-batches --dry-run  # only list what would expire
python -m inventory_service.cli expire-batches --dry-run --today 2027-01-01
"""

import argparse
import asyncio
import json
import sys
from datetime import date

from pharmacy_shared import clock

from .db import db
from .services.expiry import expire_batches


async def _expire(today: date, dry_run: bool) -> list | None:
    try:
        async with db.sessionmaker() as session:
            return await expire_batches(session, today, dry_run=dry_run)
    finally:
        await db.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="inventory_service.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("expire-batches", help="mark active batches past expiry as expired")
    cmd.add_argument("--dry-run", action="store_true", help="only list, change nothing")
    cmd.add_argument(
        "--today", type=date.fromisoformat, help="pretend today is this date (only with --dry-run)"
    )
    args = parser.parse_args(argv)
    if args.today and not args.dry_run:
        parser.error("--today is only allowed with --dry-run")
    results = asyncio.run(_expire(args.today or clock.today(), args.dry_run))
    if results is None:
        print("Another replica is running the expiry job; nothing done.")
        return 1
    print(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"{'Would expire' if args.dry_run else 'Expired'} {len(results)} batch(es)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
