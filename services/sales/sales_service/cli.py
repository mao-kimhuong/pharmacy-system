"""Sales admin commands.

python -m sales_service.cli recover     # finish sales/returns left half-way (what the task does every minute)
python -m sales_service.cli republish   # commission lines and periods as events again (make resync)
python -m sales_service.cli payway-check [--qr]
    The PayWay settings, then check-transaction for a made-up tran_id: PayWay must answer 6 (not found), which
    proves the URL, merchant id and signing. --qr (sandbox only) also makes a 100 KHR QR. Prints no secret.
python -m sales_service.cli khqr-reconcile [--date YYYY-MM-DD]
    The daily KHQR check now (default: yesterday, Asia/Phnom_Penh).
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


async def _payway_check(with_qr: bool) -> int:
    """0 when PayWay answers as expected. Output: setting names, PayWay's codes and messages; never values."""
    import secrets
    from decimal import Decimal
    from urllib.parse import urlsplit

    from pharmacy_shared.errors import AppError

    from .services import payway

    settings = get_settings()
    try:
        payway.check_settings(settings)
    except RuntimeError as exc:
        print(f"FAIL settings: {exc}")
        return 1
    print("ok   settings: PAYWAY_BASE_URL, PAYWAY_MERCHANT_ID, PAYWAY_API_KEY, PAYWAY_RSA_PUBLIC_KEY_FILE")
    api = payway.PayWay(settings)
    host = urlsplit(api.root).hostname or ""
    print(f"     PayWay host: {host}")
    fake = f"CHK{secrets.randbelow(10**12):012d}"
    try:
        c = await api.check(fake)
    except AppError as exc:
        print(f"FAIL check-transaction: {exc.code} {exc.message}")
        return 1
    if c.code != payway.CHECK_NOT_FOUND:
        hint = {"5": "invalid hash: check PAYWAY_API_KEY", "8": "invalid merchant: check PAYWAY_MERCHANT_ID"}
        print(f"FAIL check-transaction answered status {c.code or '?'} (expected 6, not found): "
              f"{hint.get(c.code, 'see the PayWay docs')}")
        return 1
    print("ok   check-transaction of a made-up tran_id: status 6 (transaction not found) – URL, merchant and hash work")
    if with_qr:
        if "sandbox" not in host:
            print("skip --qr: only against the sandbox (it creates a real transaction)")
            return 0
        tran = f"CHK{secrets.randbelow(10**12):012d}"
        try:
            qr = await api.generate_qr(tran, Decimal("100"), "KHR", 3)
        except AppError as exc:
            print(f"FAIL generate-qr: {exc.code} {exc.message}")
            return 1
        print(f"ok   generate-qr: a 100 KHR sandbox QR (tran_id {tran}, {len(qr.qr_string)} characters)")
        c = await api.check(tran)
        print(f"ok   check-transaction of it: status {c.code}, payment_status_code {c.payment_status_code}"
              if c.code == "00" else f"FAIL check-transaction of it: status {c.code}")  # fmt: skip
        return 0 if c.code == "00" else 1
    return 0


async def _reconcile(day: str | None) -> dict:
    from datetime import date, timedelta

    from pharmacy_shared import clock

    from .services.khqr import reconcile

    try:
        async with db.sessionmaker() as session:
            return await reconcile(session, date.fromisoformat(day) if day else clock.today() - timedelta(days=1))
    finally:
        await db.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sales_service.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("recover", help="compensate / finish sagas left pending")
    sub.add_parser("republish", help="send commission lines and periods as events again")
    check = sub.add_parser("payway-check", help="PayWay settings + a check-transaction that must answer 6")
    check.add_argument("--qr", action="store_true", help="sandbox only: also make a 100 KHR QR")
    rec = sub.add_parser("khqr-reconcile", help="the daily KHQR check now")
    rec.add_argument("--date", help="YYYY-MM-DD (default: yesterday)")
    args = parser.parse_args(argv)
    if args.command == "payway-check":
        return asyncio.run(_payway_check(args.qr))
    if args.command == "khqr-reconcile":
        print(json.dumps(asyncio.run(_reconcile(args.date))))
        return 0
    if args.command == "recover":
        print(json.dumps(asyncio.run(_recover())))
    elif args.command == "republish":
        print(f"{asyncio.run(_republish())} commission lines republished")
    return 0


if __name__ == "__main__":
    sys.exit(main())
