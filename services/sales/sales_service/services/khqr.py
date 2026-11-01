"""KHQR (Bakong) payments. Rules:

- POST /payments/khqr (pos.sell, Idempotency-Key): a dynamic KHQR for an amount in
  USD (cents) or KHR (whole hundreds of riel) of the branch's Bakong account (branch setting
  `khqr`), else the shared account (settings KHQR_*). Valid KHQR_EXPIRES_SECONDS.
- The status is asked from the provider: GET /payments/khqr/{id} (answer cached
  2 s in Redis) and a background task every 5 s for pending rows; past expires_at
  → expired.
- A sale pays with it: payments[{method: "KHQR", khqr_id, amount, currency}]; the
  QR must be paid, of the same branch, amount and currency, and unused; saving the
  sale marks it used (row locked; invoice_payments.khqr_id is unique). If that sale
  then fails, the money is with us: the QR becomes needs_refund (Telegram alert via
  khqr.needs_refund); refunds are done by hand at the bank, never automatically.
- Providers: FakeProvider (tests, development: deterministic QR, paid by
  POST /internal/v1/khqr/fake/{id}/pay) and BakongProvider (EMV-KHQR string with
  tag 29 individual / 30 merchant account, CRC16-CCITT; the NBC Open API
  check_transaction_by_md5 with the API token). Production refuses the fake.
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.outbox import add_event

from ..config import Settings, get_settings
from ..models import BranchSettingsCopy, KhqrPayment, OutboxEvent
from .common import audit, branch_for

log = logging.getLogger(__name__)
CURRENCY_CODE = {"USD": "840", "KHR": "116"}
CACHE_SECONDS = 2


# ---------------------------------------------------------------- the EMV-KHQR string


def _tlv(tag: str, value: str) -> str:
    return f"{tag}{len(value):02d}{value}"


def crc16(data: str) -> str:
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF), as EMV QR requires."""
    crc = 0xFFFF
    for byte in data.encode():
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return f"{crc:04X}"


def khqr_string(account: dict[str, Any], amount: Decimal, currency: str, bill_no: str, expires_at: datetime,
                mcc: str = "5912") -> str:  # fmt: skip
    """A dynamic KHQR: individual (tag 29) or merchant (tag 30, with the bank's merchant id)."""
    merchant = bool(account.get("merchant_id"))
    acc = _tlv("00", account["account_id"])
    if merchant:
        acc += _tlv("01", account["merchant_id"]) + _tlv("02", account.get("acquiring_bank") or "")
    amount_text = f"{amount:.2f}" if currency == "USD" else f"{int(amount)}"
    stamp = _tlv("00", str(int(clock.now().timestamp() * 1000))) + _tlv("01", str(int(expires_at.timestamp() * 1000)))
    body = (_tlv("00", "01") + _tlv("01", "12") + _tlv("30" if merchant else "29", acc) + _tlv("52", mcc)
            + _tlv("53", CURRENCY_CODE[currency]) + _tlv("54", amount_text) + _tlv("58", "KH")
            + _tlv("59", account["merchant_name"][:25]) + _tlv("60", (account.get("city") or "Phnom Penh")[:15])
            + _tlv("62", _tlv("01", bill_no[:25])) + _tlv("99", stamp) + "6304")  # fmt: skip
    return body + crc16(body)


# ---------------------------------------------------------------- providers


@dataclass
class Status:
    status: str  # pending | paid
    paid_amount: Decimal | None = None
    bank_ref: str | None = None
    paid_at: datetime | None = None


class Provider(Protocol):
    async def status(self, md5: str) -> Status: ...


class FakeProvider:
    """Tests and development: nothing leaves the server; mark_paid() pays."""

    paid: dict[str, Status] = {}

    async def status(self, md5: str) -> Status:
        return self.paid.get(md5, Status("pending"))

    @classmethod
    def mark_paid(cls, md5: str, amount: Decimal) -> None:
        cls.paid[md5] = Status("paid", amount, f"FAKE-{md5[:10]}", clock.now())


class BakongProvider:
    """NBC Bakong Open API: POST /v1/check_transaction_by_md5 (Bearer token)."""

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings, self.transport = settings, transport

    async def status(self, md5: str) -> Status:
        url = f"{self.settings.bakong_api_base}/v1/check_transaction_by_md5"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(8, connect=3), transport=self.transport) as client:
                r = await client.post(url, json={"md5": md5},
                                      headers={"Authorization": f"Bearer {self.settings.bakong_token}"})  # fmt: skip
            body = r.json() if r.content else {}
        except (httpx.HTTPError, ValueError) as exc:
            raise AppError(ErrorCode.TEMPORARILY_UNAVAILABLE, "Bakong cannot be reached; try again",
                           status_code=503) from exc  # fmt: skip
        if r.status_code >= 400:
            raise AppError(ErrorCode.TEMPORARILY_UNAVAILABLE, f"Bakong answered {r.status_code}", status_code=503)
        if body.get("responseCode") == 0 and body.get("data"):
            d = body["data"]
            return Status("paid", Decimal(str(d.get("amount"))), str(d.get("hash") or d.get("externalRef") or ""),
                          clock.now())  # fmt: skip
        return Status("pending")


def provider(settings: Settings | None = None) -> Provider:
    s = settings or get_settings()
    return BakongProvider(s) if s.khqr_provider == "bakong" else FakeProvider()


# ---------------------------------------------------------------- the payments


async def account_for(session: AsyncSession, branch_id: UUID, settings: Settings) -> dict[str, Any]:
    row = await session.get(BranchSettingsCopy, branch_id)
    if row is not None and row.khqr:
        return dict(row.khqr)
    if not settings.khqr_account_id:
        raise AppError(ErrorCode.VALIDATION_ERROR, "No KHQR account: set the branch's or the shared one",
                       status_code=422)  # fmt: skip
    return {"account_id": settings.khqr_account_id, "merchant_name": settings.khqr_merchant_name,
            "city": settings.khqr_city, "merchant_id": settings.khqr_merchant_id or None,
            "acquiring_bank": settings.khqr_acquiring_bank or None, "currencies": ["USD", "KHR"]}  # fmt: skip


async def create(session: AsyncSession, actor: CurrentUser, data: dict[str, Any]) -> KhqrPayment:
    settings = get_settings()
    branch = await branch_for(session, actor, data["branch_id"])
    account = await account_for(session, branch.id, settings)
    currency = data["currency"]
    if currency not in (account.get("currencies") or ["USD", "KHR"]):
        raise AppError(ErrorCode.VALIDATION_ERROR, f"This branch's KHQR account does not take {currency}",
                       status_code=422)  # fmt: skip
    amount = Decimal(str(data["amount"]))
    if currency == "KHR" and amount % 100:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Riel in whole hundreds (as every riel payment)", status_code=422)
    expires_at = clock.now() + timedelta(seconds=settings.khqr_expires_seconds)
    bill_no = f"{branch.code}-{clock.now():%y%m%d%H%M%S}"
    qr = khqr_string(account, amount, currency, bill_no, expires_at, settings.khqr_mcc)
    p = KhqrPayment(branch_id=branch.id, cart_ref=data.get("cart_ref") or "", amount=amount, currency=currency,
                    qr_string=qr, md5=hashlib.md5(qr.encode()).hexdigest(), account_id=account["account_id"],  # noqa: S324 – Bakong's id
                    status="pending", expires_at=expires_at, created_by=actor.id)  # fmt: skip
    session.add(p)
    await session.flush()
    audit(session, actor, "khqr.created", "khqr_payment", p.id, branch_id=branch.id,
          after={"amount": str(amount), "currency": currency, "account": account["account_id"]})  # fmt: skip
    await session.commit()
    return p


async def get(session: AsyncSession, actor: CurrentUser, khqr_id: UUID, *, lock: bool = False) -> KhqrPayment:
    query = select(KhqrPayment).where(KhqrPayment.id == khqr_id)
    p = (await session.execute(query.with_for_update() if lock else query)).scalar_one_or_none()
    if p is None or not actor.can_access_branch(p.branch_id):
        raise AppError(ErrorCode.NOT_FOUND, "KHQR payment not found", status_code=404)
    return p


async def refresh(session: AsyncSession, p: KhqrPayment, prov: Provider | None = None, redis: Any = None) -> None:
    """Asks the provider about a pending QR (at most every 2 s per QR); expires old ones."""
    if p.status != "pending":
        return
    if redis is not None:
        try:
            if not await redis.set(f"khqr:checked:{p.id}", "1", ex=CACHE_SECONDS, nx=True):
                return
        except Exception:  # noqa: BLE001 – no cache: just ask
            log.debug("khqr cache unavailable")
    st = await (prov or provider()).status(p.md5)
    if st.status == "paid":
        p.status, p.paid_amount, p.bank_ref, p.paid_at = "paid", st.paid_amount, st.bank_ref, st.paid_at
    elif p.expires_at <= clock.now():
        p.status = "expired"


async def check_for_sale(session: AsyncSession, actor: CurrentUser, branch_id: UUID, khqr_id: UUID, currency: str,
                         amount: Decimal, *, lock: bool) -> KhqrPayment:  # fmt: skip
    """A sale paying with this QR: paid, same branch, amount and currency, unused."""
    p = await get(session, actor, khqr_id, lock=lock)
    await refresh(session, p)
    details = {"khqr_id": str(p.id), "status": p.status}
    if p.branch_id != branch_id:
        raise AppError(ErrorCode.KHQR_MISMATCH, "This KHQR belongs to another branch", status_code=422, details=details)
    if p.status in ("used", "needs_refund"):
        raise AppError(ErrorCode.KHQR_USED, "This KHQR payment was used for another sale", status_code=409,
                       details={**details, "invoice_id": str(p.invoice_id) if p.invoice_id else None})  # fmt: skip
    if p.status != "paid":
        raise AppError(ErrorCode.KHQR_NOT_PAID, f"The KHQR payment is {p.status}", status_code=409, details=details)
    if p.currency != currency or p.amount != amount or (p.paid_amount is not None and p.paid_amount != p.amount):
        raise AppError(ErrorCode.KHQR_MISMATCH, f"The KHQR was for {p.amount} {p.currency}", status_code=422,
                       details={**details, "amount": str(p.amount), "currency": p.currency})  # fmt: skip
    return p


def needs_refund(session: AsyncSession, p: KhqrPayment, reason: str) -> None:
    p.status = "needs_refund"
    add_event(session, OutboxEvent, "khqr.needs_refund", {
        "khqr_id": str(p.id), "branch_id": str(p.branch_id), "amount": str(p.amount), "currency": p.currency,
        "bank_ref": p.bank_ref, "invoice_id": str(p.invoice_id) if p.invoice_id else None, "reason": reason[:200],
        "occurred_at": clock.now().isoformat()})  # fmt: skip
    audit(session, None, "khqr.needs_refund", "khqr_payment", p.id, branch_id=p.branch_id,
          after={"amount": str(p.amount), "currency": p.currency, "reason": reason[:200]})  # fmt: skip


async def poll_pending(session: AsyncSession, prov: Provider | None = None) -> int:
    rows = list((await session.execute(select(KhqrPayment).where(KhqrPayment.status == "pending")
                                       .with_for_update(skip_locked=True).limit(50))).scalars())  # fmt: skip
    for p in rows:
        try:
            await refresh(session, p, prov)
        except AppError:
            log.warning("khqr status of %s not known yet", p.id)
    await session.commit()
    return len(rows)
