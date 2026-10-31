"""Reports admin commands.

python -m reports_service.cli backfill [--rebuild] [--service sales ...]
    Replay the services' outboxes into the read models (safe to run again).
python -m reports_service.cli seed-demo [--days 365] [--invoices 250]
    One year of demo data for the DEMO branches (APP_ENV=development only).
python -m reports_service.cli bench
    Time every report and the dashboard over the last year (target < 2 s each).
"""

import argparse
import asyncio
import json
import sys

from .config import get_settings
from .db import db


async def _backfill(services: list[str] | None, rebuild: bool) -> dict:
    from .services.backfill import backfill

    try:
        return await backfill(db, get_settings(), services, rebuild)
    finally:
        await db.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reports_service.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("backfill", help="replay the services' outboxes into the read models")
    b.add_argument("--rebuild", action="store_true", help="empty the read models first")
    b.add_argument("--service", action="append", help="only this service (repeatable)")
    s = sub.add_parser("seed-demo", help="a year of demo data (APP_ENV=development, DEMO branches)")
    s.add_argument("--days", type=int, default=365)
    s.add_argument("--invoices", type=int, default=250, help="invoices per branch per day")
    sub.add_parser("bench", help="time every report over the last year")
    args = parser.parse_args(argv)
    if args.command == "backfill":
        print(json.dumps(asyncio.run(_backfill(args.service, args.rebuild)), indent=2))
    elif args.command == "seed-demo":
        from .services.demo import run

        print(json.dumps(asyncio.run(run(db, args.days, args.invoices)), indent=2))
    elif args.command == "bench":
        from .services.bench import run as bench

        rows = asyncio.run(bench(db))
        print(f"{'report':<26}{'seconds':>9}{'rows':>10}")
        for key, seconds, total in rows:
            flag = "" if seconds < 2 else "  SLOW"
            print(f"{key:<26}{seconds:>9.3f}{total:>10}{flag}")
        return 0 if all(s < 2 for _, s, _ in rows) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
