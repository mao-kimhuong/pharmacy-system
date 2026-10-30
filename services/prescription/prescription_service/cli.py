"""Prescription admin commands.

python -m prescription_service.cli expire-prescriptions   # what the 00:10 job does, now
"""

import argparse
import asyncio
import json
import sys

from pharmacy_shared import clock

from .db import db
from .services.expiry import expire_prescriptions


async def _expire() -> list[str] | None:
    try:
        async with db.sessionmaker() as session:
            return await expire_prescriptions(session, clock.today())
    finally:
        await db.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="prescription_service.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("expire-prescriptions", help="mark open prescriptions past valid_until as expired")
    parser.parse_args(argv)
    results = asyncio.run(_expire())
    if results is None:
        print("Another replica is running the expiry job; nothing done.")
        return 1
    print(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"Expired {len(results)} prescription(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
