"""KHQR payments. Rules:

- POST /payments/khqr (pos.sell, Idempotency-Key): a dynamic KHQR for an amount in USD (cents) or KHR
  (whole hundreds of riel), valid KHQR_EXPIRES_SECONDS. Bakong / fake: an EMV-KHQR of the branch's Bakong
  account (branch setting `khqr`) or the shared one (KHQR_*). PayWay: ABA's QR API makes it, on our own
  `tran_id` (≤ 20 characters, unique).
- The status is asked from the provider: GET /payments/khqr/{id} (answer cached 2 s in Redis), PayWay's
  callback (POST /payments/payway/callback: it only makes us ask, it is not trusted) and a background task every
  5 s for pending rows; past expires_at → expired (closed at PayWay). POST /payments/khqr/{id}/cancel: a pending
  QR given up → cancelled (closed at PayWay).
- Paid: only when the provider says paid AND the paid amount and currency are the QR's; otherwise → review (a
  manager looks, Telegram, the money is due back). Paid after it expired or was cancelled → needs_refund.
  Expired / cancelled QRs are still asked about for KHQR_LATE_CHECK_HOURS (every KHQR_LATE_CHECK_EVERY_SECONDS).
- A sale pays with it: payments[{method: "KHQR", khqr_id, amount, currency}]; the QR must be paid, of the same
  branch, amount and currency, and unused; saving the sale marks it used (row locked; invoice_payments.khqr_id is
  unique). If that sale fails or is cancelled → needs_refund; a return with refund_method "khqr" → a refund due.
- Refunds (khqr_refunds, once per payment + source): never automatic. POST /payments/khqr/refunds/{id}/refund
  (sales.khqr_refund: owner, branch manager; own branch; PIN, action sales.khqr_refund; Idempotency-Key):
  PayWay refund API; Bakong has none: the person confirms they refunded at the bank (method by_hand).
- Every day at 00:40 Asia/Phnom_Penh (and at start-up) yesterday's QRs are compared with the provider; mismatches
  go to khqr_reconcile_issues (GET /payments/khqr/reconciliation) and Telegram.
- Providers: FakeProvider (tests, development: deterministic QR, paid by POST /internal/v1/khqr/fake/{id}/pay),
  BakongProvider (EMV-KHQR, tag 29 individual / 30 merchant, CRC16-CCITT; NBC check_transaction_by_md5) and
  PayWayProvider (services/payway.py). Production refuses the fake.
"""

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID, uuid4

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.outbox import add_event

from ..config import Settings, get_settings
from ..models import BranchSettingsCopy, KhqrPayment, KhqrReconcileIssue, KhqrRefund, OutboxEvent
from .common import audit, branch_for

log = logging.getLogger(__name__)
CURRENCY_CODE = {"USD": "840", "KHR": "116"}
CACHE_SECONDS = 2
SETTLED = ("paid", "used", "review", "needs_refund", "refunded")
REFUND_PIN_ACTION = "sales.khqr_refund"
RECONCILE_LOCK = 0x6B687172  # "khqr"


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
    status: str  # pending | paid | cancelled | refunded
    paid_amount: Decimal | None = None
    bank_ref: str | None = None
    paid_at: datetime | None = None
    paid_currency: str | None = None
    refunded: Decimal = Decimal("0")


class Provider(Protocol):
    name: str

    async def make(self, p: KhqrPayment, account: dict[str, Any], settings: Settings) -> None: ...
    async def status(self, p: KhqrPayment) -> Status: ...
    async def close(self, p: KhqrPayment) -> None: ...
    async def refund(self, p: KhqrPayment, amount: Decimal) -> str: ...  # the method: payway | by_hand | fake


def _emv(p: KhqrPayment, account: dict[str, Any], settings: Settings, bill_no: str) -> None:
    p.qr_string = khqr_string(account, p.amount, p.currency, bill_no, p.expires_at, settings.khqr_mcc)
    p.md5 = hashlib.md5(p.qr_string.encode()).hexdigest()  # noqa: S324 – Bakong's id for the QR
    p.account_id = account["account_id"]


class FakeProvider:
    """Tests and development: nothing leaves the server; mark_paid() pays, refunds always work."""

    name = "fake"
    paid: dict[str, Status] = {}
    refunded: dict[str, Decimal] = {}

    async def make(self, p: KhqrPayment, account: dict[str, Any], settings: Settings) -> None:
        _emv(p, account, settings, account["bill_no"])

    async def status(self, p: KhqrPayment) -> Status:
        st = self.paid.get(p.md5, Status("pending"))
        return Status(st.status, st.paid_amount, st.bank_ref, st.paid_at, st.paid_currency,
                      self.refunded.get(p.md5, Decimal("0")))  # fmt: skip

    async def close(self, p: KhqrPayment) -> None:
        return None

    async def refund(self, p: KhqrPayment, amount: Decimal) -> str:
        self.refunded[p.md5] = self.refunded.get(p.md5, Decimal("0")) + amount
        return "fake"

    @classmethod
    def mark_paid(cls, md5: str, amount: Decimal, currency: str | None = None) -> None:
        cls.paid[md5] = Status("paid", amount, f"FAKE-{md5[:10]}", clock.now(), currency)


class BakongProvider:
    """NBC Bakong Open API: POST /v1/check_transaction_by_md5 (Bearer token). No refund API: by hand."""

    name = "bakong"

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings, self.transport = settings, transport

    async def make(self, p: KhqrPayment, account: dict[str, Any], settings: Settings) -> None:
        _emv(p, account, settings, account["bill_no"])

    async def status(self, p: KhqrPayment | str) -> Status:
        md5 = p if isinstance(p, str) else p.md5
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
                          clock.now(), (d.get("currency") or "").upper() or None)  # fmt: skip
        return Status("pending")

    async def close(self, p: KhqrPayment) -> None:
        return None  # a Bakong KHQR cannot be closed: a late payment is caught by the late check

    async def refund(self, p: KhqrPayment, amount: Decimal) -> str:
        return "by_hand"


class PayWayProvider:
    """ABA PayWay (services/payway.py): the QR on our tran_id, check-transaction-2, close, refund."""

    name = "payway"

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        from .payway import PayWay

        self.api = PayWay(settings, transport)

    async def make(self, p: KhqrPayment, account: dict[str, Any], settings: Settings) -> None:
        from .payway import lifetime_minutes

        p.tran_id = f"K{clock.now():%y%m%d%H%M%S}{secrets.randbelow(10**6):06d}"  # 19 characters, unique
        qr = await self.api.generate_qr(p.tran_id, p.amount, p.currency, lifetime_minutes(settings.khqr_expires_seconds))
        p.qr_string, p.deeplink = qr.qr_string, qr.deeplink
        p.md5 = hashlib.md5(qr.qr_string.encode()).hexdigest()  # noqa: S324 – an id, as for Bakong
        p.account_id = f"payway:{settings.payway_merchant_id}"[:40]

    async def status(self, p: KhqrPayment) -> Status:
        from . import payway

        c = await self.api.check(p.tran_id or "")
        if c.code == payway.CHECK_NOT_FOUND:
            return Status("pending")
        if c.code != "00":
            raise AppError(ErrorCode.PAYWAY_REJECTED, "ABA PayWay refused the status check", status_code=502,
                           details={"provider_code": c.code})  # fmt: skip
        if c.payment_status_code in (payway.PAID, payway.REFUNDED):
            return Status("paid", c.payment_amount, c.apv, clock.now(), c.payment_currency, c.refund_amount)
        if c.payment_status_code == payway.CANCELLED:
            return Status("cancelled")
        return Status("pending")  # 2 pending, 3 declined: the customer may still pay

    async def close(self, p: KhqrPayment) -> None:
        if p.tran_id:
            code = await self.api.close(p.tran_id)
            if code not in ("00", "5"):  # 5 = not found (never scanned): nothing to close
                log.warning("PayWay close of %s: code %s", p.tran_id, code)

    async def refund(self, p: KhqrPayment, amount: Decimal) -> str:
        await self.api.refund(p.tran_id or "", amount)
        return "payway"


def provider(settings: Settings | None = None, name: str | None = None) -> Provider:
    s = settings or get_settings()
    name = name or s.khqr_provider
    if name == "payway":
        return PayWayProvider(s)
    return BakongProvider(s) if name == "bakong" else FakeProvider()


def provider_for(p: KhqrPayment) -> Provider:
    """The provider that made this QR (a payment made before a switch keeps its own)."""
    return provider(name=p.provider)


# ---------------------------------------------------------------- the payments


async def account_for(session: AsyncSession, branch_id: UUID, settings: Settings) -> dict[str, Any]:
    if settings.khqr_provider == "payway":  # PayWay's merchant takes both currencies
        return {"account_id": f"payway:{settings.payway_merchant_id}"[:40], "currencies": ["USD", "KHR"]}
    row = await session.get(BranchSettingsCopy, branch_id)
    if row is not None and row.khqr:
        return dict(row.khqr)
    if not settings.khqr_account_id:
        raise AppError(ErrorCode.VALIDATION_ERROR, "No KHQR account: set the branch's or the shared one",
                       status_code=422)  # fmt: skip
    return {"account_id": settings.khqr_account_id, "merchant_name": settings.khqr_merchant_name,
            "city": settings.khqr_city, "merchant_id": settings.khqr_merchant_id or None,
            "acquiring_bank": settings.khqr_acquiring_bank or None, "currencies": ["USD", "KHR"]}  # fmt: skip


async def create(session: AsyncSession, actor: CurrentUser, data: dict[str, Any],
                 prov: Provider | None = None) -> KhqrPayment:  # fmt: skip
    settings = get_settings()
    prov = prov or provider(settings)
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
    p = KhqrPayment(branch_id=branch.id, cart_ref=data.get("cart_ref") or "",
                    amount=amount, currency=currency, provider=prov.name, status="pending", expires_at=expires_at,
                    created_by=actor.id, refunded_amount=Decimal("0"), created_at=clock.now())  # fmt: skip
    # a random tail: two tills asking the same amount in the same millisecond must not get the same QR (md5 unique)
    bill_no = f"{branch.code}-{clock.now():%y%m%d%H%M%S}-{secrets.token_hex(2)}"
    await prov.make(p, {**account, "bill_no": bill_no}, settings)
    session.add(p)
    await session.flush()
    audit(session, actor, "khqr.created", "khqr_payment", p.id, branch_id=branch.id,
          after={"amount": str(amount), "currency": currency, "account": p.account_id, "provider": prov.name})  # fmt: skip
    await session.commit()
    return p


async def create_checkout(session: AsyncSession, actor: CurrentUser, data: dict[str, Any],
                          prov: Provider | None = None) -> tuple[KhqrPayment, dict[str, Any] | None]:  # fmt: skip
    """PayWay Purchase at the till: a payment attempt on our own tran_id and the signed form the browser posts to
    PayWay's hosted checkout (cards, ABA PAY, KHQR, wallets). Paid / cancelled / refunded exactly like a KHQR
    (check-transaction, the callback, close, the refund API). The fake provider (development) has no form: the
    owner marks it paid. Bakong has no checkout."""
    settings = get_settings()
    prov = prov or provider(settings)
    if prov.name == "bakong":
        raise AppError(ErrorCode.VALIDATION_ERROR, "PayWay checkout needs KHQR_PROVIDER=payway", status_code=422)
    branch = await branch_for(session, actor, data["branch_id"])
    currency, amount = data["currency"], Decimal(str(data["amount"]))
    if currency == "KHR" and amount % 100:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Riel in whole hundreds (as every riel payment)", status_code=422)
    p = KhqrPayment(id=uuid4(), branch_id=branch.id, cart_ref=data.get("cart_ref") or "", kind="checkout",
                    payment_option=data.get("payment_option") or None, amount=amount, currency=currency,
                    provider=prov.name, status="pending", created_by=actor.id, refunded_amount=Decimal("0"),
                    expires_at=clock.now() + timedelta(minutes=settings.payway_checkout_minutes), created_at=clock.now(),
                    tran_id=f"P{clock.now():%y%m%d%H%M%S}{secrets.randbelow(10**6):06d}", qr_string="",
                    account_id=f"{prov.name}:{settings.payway_merchant_id}"[:40] if prov.name == "payway" else "fake")  # fmt: skip
    p.md5 = hashlib.md5(p.tran_id.encode()).hexdigest()  # noqa: S324 – only an id (unique), as for the QRs
    form = None
    if isinstance(prov, PayWayProvider):
        web = settings.payway_web_url.rstrip("/")
        back = f"{web}/pos/payway-return?id={p.id}"
        form = {"action": prov.api.purchase_url, "fields": prov.api.checkout_form(
            p.tran_id, amount, currency, p.payment_option or "", settings.payway_checkout_minutes,
            cancel_url=back + "&result=cancel", continue_success_url=back + "&result=done")}  # fmt: skip
    session.add(p)
    await session.flush()
    audit(session, actor, "khqr.checkout_created", "khqr_payment", p.id, branch_id=branch.id,
          after={"amount": str(amount), "currency": currency, "provider": prov.name,
                 "payment_option": p.payment_option})  # fmt: skip
    await session.commit()
    return p, form


async def get(session: AsyncSession, actor: CurrentUser, khqr_id: UUID, *, lock: bool = False) -> KhqrPayment:
    query = select(KhqrPayment).where(KhqrPayment.id == khqr_id)
    p = (await session.execute(query.with_for_update() if lock else query)).scalar_one_or_none()
    if p is None or not actor.can_access_branch(p.branch_id):
        raise AppError(ErrorCode.NOT_FOUND, "KHQR payment not found", status_code=404)
    return p


async def refresh(session: AsyncSession, p: KhqrPayment, prov: Provider | None = None, redis: Any = None,  # noqa: ANN401
                  *, force: bool = False) -> None:  # fmt: skip
    """Asks the provider about a QR not settled yet (at most every 2 s per QR). Pending: paid / review /
    cancelled at the provider / expired. Expired or cancelled (for KHQR_LATE_CHECK_HOURS, every
    KHQR_LATE_CHECK_EVERY_SECONDS): a late payment → needs_refund."""
    settings = get_settings()
    now = clock.now()
    if p.status in SETTLED:
        return
    if p.status != "pending":
        if p.expires_at < now - timedelta(hours=settings.khqr_late_check_hours):
            return
        if not force and p.checked_at and p.checked_at > now - timedelta(seconds=settings.khqr_late_check_every_seconds):
            return
    if redis is not None and not force:
        try:
            if not await redis.set(f"khqr:checked:{p.id}", "1", ex=CACHE_SECONDS, nx=True):
                return
        except Exception:  # noqa: BLE001 – no cache: just ask
            log.debug("khqr cache unavailable")
    prov = prov or provider_for(p)
    p.checked_at = now
    st = await prov.status(p)
    if st.status == "paid":
        _paid(session, p, st)
    elif p.status == "pending" and st.status == "cancelled":
        p.status = "cancelled"
    elif p.status == "pending" and p.expires_at <= now:
        p.status = "expired"
        await _close(prov, p)


async def _close(prov: Provider, p: KhqrPayment) -> None:
    try:
        await prov.close(p)
    except AppError as err:  # the late check still catches a payment that slips through
        log.warning("khqr %s not closed at the provider: %s", p.id, err.code)


def _paid(session: AsyncSession, p: KhqrPayment, st: Status) -> None:
    was = p.status
    paid = st.paid_amount.quantize(Decimal("0.01")) if st.paid_amount is not None else None  # PayWay: 0.5 → 0.50
    p.paid_amount, p.paid_currency = paid, st.paid_currency or p.currency
    p.bank_ref, p.paid_at = st.bank_ref, st.paid_at or clock.now()
    if was in ("expired", "cancelled"):
        needs_refund(session, p, f"Paid after the QR was {was}", source="late_payment", ref="late")
        return
    if p.paid_amount != p.amount or p.paid_currency != p.currency:
        p.status = "review"
        p.review_reason = (f"Paid {p.paid_amount} {p.paid_currency}, the QR was for {p.amount} {p.currency}")[:200]
        due(session, p, "review", "review", p.review_reason, amount=p.paid_amount if p.paid_currency == p.currency
            else p.amount)  # fmt: skip
        add_event(session, OutboxEvent, "khqr.review", {
            "khqr_id": str(p.id), "branch_id": str(p.branch_id), "amount": str(p.amount), "currency": p.currency,
            "paid_amount": str(p.paid_amount), "paid_currency": p.paid_currency, "bank_ref": p.bank_ref,
            "occurred_at": clock.now().isoformat()})  # fmt: skip
        audit(session, None, "khqr.review", "khqr_payment", p.id, branch_id=p.branch_id,
              after={"reason": p.review_reason})  # fmt: skip
        return
    p.status = "paid"


async def cancel(session: AsyncSession, actor: CurrentUser, khqr_id: UUID, prov: Provider | None = None) -> KhqrPayment:
    """The till gives up a pending QR: closed at the provider; a payment that still arrives → needs_refund."""
    p = await get(session, actor, khqr_id, lock=True)
    if p.status == "cancelled":
        return p
    prov = prov or provider_for(p)
    if p.status == "pending":
        await refresh(session, p, prov, force=True)  # paid a second ago? then it is not given up
    if p.status != "pending":
        raise AppError(ErrorCode.KHQR_STATE, f"The KHQR payment is {p.status}: it cannot be cancelled",
                       status_code=409, details={"khqr_id": str(p.id), "status": p.status})  # fmt: skip
    p.status, p.cancelled_at, p.cancelled_by = "cancelled", clock.now(), actor.id
    await _close(prov, p)
    audit(session, actor, "khqr.cancelled", "khqr_payment", p.id, branch_id=p.branch_id,
          after={"amount": str(p.amount), "currency": p.currency})  # fmt: skip
    await session.commit()
    return p


async def check_for_sale(session: AsyncSession, actor: CurrentUser, branch_id: UUID, khqr_id: UUID, currency: str,
                         amount: Decimal, *, lock: bool, kind: str = "khqr") -> KhqrPayment:  # fmt: skip
    """A sale paying with this QR (method KHQR) or PayWay checkout (method PAYWAY): paid, same branch, amount and
    currency, unused."""
    p = await get(session, actor, khqr_id, lock=lock)
    details = {"khqr_id": str(p.id), "status": p.status}
    if p.kind != kind:
        raise AppError(ErrorCode.KHQR_MISMATCH, "This payment is a " + ("PayWay checkout: pay with method PAYWAY"
                       if p.kind == "checkout" else "KHQR: pay with method KHQR"), status_code=422, details=details)  # fmt: skip
    await refresh(session, p)
    details = {"khqr_id": str(p.id), "status": p.status}
    if p.branch_id != branch_id:
        raise AppError(ErrorCode.KHQR_MISMATCH, "This KHQR belongs to another branch", status_code=422, details=details)
    if p.status in ("used", "needs_refund", "refunded"):
        raise AppError(ErrorCode.KHQR_USED, "This KHQR payment was used for another sale", status_code=409,
                       details={**details, "invoice_id": str(p.invoice_id) if p.invoice_id else None})  # fmt: skip
    if p.status == "review":
        raise AppError(ErrorCode.KHQR_MISMATCH, f"{p.review_reason}: a manager must check it", status_code=422,
                       details={**details, "amount": str(p.amount), "currency": p.currency})  # fmt: skip
    if p.status != "paid":
        raise AppError(ErrorCode.KHQR_NOT_PAID, f"The KHQR payment is {p.status}", status_code=409, details=details)
    if p.currency != currency or p.amount != amount:
        raise AppError(ErrorCode.KHQR_MISMATCH, f"The KHQR was for {p.amount} {p.currency}", status_code=422,
                       details={**details, "amount": str(p.amount), "currency": p.currency})  # fmt: skip
    return p


# ---------------------------------------------------------------- refunds


async def _open_total(session: AsyncSession, p: KhqrPayment) -> Decimal:
    """Already refunded + still due or requested: what cannot be asked again."""
    due_or_asked = (await session.execute(select(func.coalesce(func.sum(KhqrRefund.amount), 0)).where(
        KhqrRefund.khqr_id == p.id, KhqrRefund.status != "refunded"))).scalar_one()  # fmt: skip
    return Decimal(p.refunded_amount or 0) + Decimal(due_or_asked)


def due(session: AsyncSession, p: KhqrPayment, source: str, ref: str, reason: str,
        amount: Decimal | None = None) -> KhqrRefund:  # fmt: skip
    """A refund to make, once per (payment, ref). The caller checked it fits what was paid."""
    r = KhqrRefund(id=uuid4(), khqr_id=p.id, branch_id=p.branch_id, source=source, source_ref=ref[:80], reason=reason[:300],
                   amount=amount if amount is not None else (p.paid_amount or p.amount), currency=p.currency,
                   status="due")  # fmt: skip
    session.add(r)
    return r


def needs_refund(session: AsyncSession, p: KhqrPayment, reason: str, *, source: str = "failed_sale",
                 ref: str | None = None) -> None:  # fmt: skip
    """No completed sale keeps this money: all of it is due back (less what was refunded already)."""
    p.status = "needs_refund"
    left = (p.paid_amount or p.amount) - Decimal(p.refunded_amount or 0)
    refund = due(session, p, source, ref or f"{source}:{p.invoice_id or p.id}", reason, left) if left > 0 else None
    add_event(session, OutboxEvent, "khqr.needs_refund", {
        "khqr_id": str(p.id), "branch_id": str(p.branch_id), "amount": str(left if left > 0 else p.amount),
        "currency": p.currency, "bank_ref": p.bank_ref, "invoice_id": str(p.invoice_id) if p.invoice_id else None,
        "reason": reason[:200], "occurred_at": clock.now().isoformat(),
        "provider": p.provider, "refund_id": str(refund.id) if refund and refund.id else None})  # fmt: skip
    audit(session, None, "khqr.needs_refund", "khqr_payment", p.id, branch_id=p.branch_id,
          after={"amount": str(p.amount), "currency": p.currency, "reason": reason[:200]})  # fmt: skip


async def return_refund_amount(session: AsyncSession, inv: Any, refund_usd: Decimal) -> tuple[KhqrPayment, Decimal]:  # noqa: ANN401
    """refund_method "khqr": the invoice's KHQR payment and the amount in its currency (KHR: at the invoice's
    rate, to 100 riel). More than is left on it → 422: the rest goes back another way."""
    from . import money

    for pay in [x for x in inv.payments if x.khqr_id]:
        p = await session.get(KhqrPayment, pay.khqr_id, with_for_update=True)
        if p is None or p.status not in ("used", "refunded"):
            continue
        amount = refund_usd if p.currency == "USD" else Decimal(money.round_riel(refund_usd * (inv.khr_per_usd or 0)))
        left = (p.paid_amount or p.amount) - await _open_total(session, p)
        if amount <= 0 or amount > left:
            raise AppError(ErrorCode.KHQR_REFUND_TOO_MUCH, f"Only {left} {p.currency} of the KHQR payment is left "
                           "to refund: give the rest back in cash", status_code=422,
                           details={"field": "refund_method", "left": str(left), "currency": p.currency})  # fmt: skip
        return p, amount
    raise AppError(ErrorCode.VALIDATION_ERROR, "This invoice was not paid by KHQR", status_code=422,
                   details={"field": "refund_method"})  # fmt: skip


async def add_return_refund(session: AsyncSession, inv: Any, ret: Any) -> None:  # noqa: ANN401
    """The return's refund is due on the KHQR payment (once per return)."""
    seen = (await session.execute(select(KhqrRefund.id).where(KhqrRefund.source_ref == f"return:{ret.id}"))).first()
    if seen:
        return
    p, amount = await return_refund_amount(session, inv, ret.refund_usd)
    due(session, p, "return", f"return:{ret.id}", f"Return {ret.number or ''} of {inv.number}".strip(), amount)


async def list_refunds(session: AsyncSession, actor: CurrentUser, branch_id: UUID | None,
                       status: str | None) -> list[tuple[KhqrRefund, KhqrPayment]]:  # fmt: skip
    query = select(KhqrRefund, KhqrPayment).join(KhqrPayment, KhqrPayment.id == KhqrRefund.khqr_id)
    if branch_id is not None:
        actor.require_branch(branch_id)
        query = query.where(KhqrRefund.branch_id == branch_id)
    elif not actor.is_owner:
        query = query.where(KhqrRefund.branch_id.in_(actor.branch_ids))
    if status:
        query = query.where(KhqrRefund.status == status)
    rows = await session.execute(query.order_by(KhqrRefund.created_at.desc()).limit(200))
    return [(r, p) for r, p in rows.all()]


async def refund(session: AsyncSession, actor: CurrentUser, refund_id: UUID, pin_token: str | None, clients: Any,  # noqa: ANN401
                 prov: Provider | None = None) -> tuple[KhqrRefund, KhqrPayment]:  # fmt: skip
    """Give the money back (sales.khqr_refund, own branch, PIN). Once: a refunded one is returned as it is; one
    left `requested` by a timeout asks the provider first whether the money already went back."""
    from pharmacy_shared.pin import consume_pin

    actor.require("sales.khqr_refund")
    r = (await session.execute(select(KhqrRefund).where(KhqrRefund.id == refund_id).with_for_update())).scalar_one_or_none()
    if r is None or not actor.can_access_branch(r.branch_id):
        raise AppError(ErrorCode.NOT_FOUND, "Refund not found", status_code=404)
    p = (await session.execute(select(KhqrPayment).where(KhqrPayment.id == r.khqr_id).with_for_update())).scalar_one()
    if r.status == "refunded":
        return r, p
    await consume_pin(clients.auth, pin_token, REFUND_PIN_ACTION, user=actor, branch_id=r.branch_id)
    prov = prov or provider_for(p)
    already = Decimal(p.refunded_amount or 0)
    if r.status == "requested":  # the last try did not hear back: did the money go?
        st = await prov.status(p)
        if st.refunded >= already + r.amount:
            return await _refunded(session, actor, r, p, r.method or prov.name)
    if already + r.amount > (p.paid_amount or p.amount):
        raise AppError(ErrorCode.KHQR_REFUND_TOO_MUCH, "The refund is more than what was paid", status_code=422)
    r.status, r.requested_at, r.last_error = "requested", clock.now(), None
    await session.commit()  # a crash or timeout from here: the next try asks the provider first
    r = (await session.execute(select(KhqrRefund).where(KhqrRefund.id == refund_id).with_for_update())).scalar_one()
    p = (await session.execute(select(KhqrPayment).where(KhqrPayment.id == r.khqr_id).with_for_update())).scalar_one()
    try:
        method = await prov.refund(p, r.amount)
    except AppError as err:
        if err.code != ErrorCode.TEMPORARILY_UNAVAILABLE:  # refused: nothing was paid out, it is due again
            r.status, r.last_error = "due", str(err.code)[:40]
            audit(session, actor, "khqr.refund_failed", "khqr_refund", r.id, branch_id=r.branch_id,
                  after={"code": str(err.code), "amount": str(r.amount), "currency": r.currency})  # fmt: skip
            await session.commit()
        raise
    return await _refunded(session, actor, r, p, method)


async def _refunded(session: AsyncSession, actor: CurrentUser, r: KhqrRefund, p: KhqrPayment,
                    method: str) -> tuple[KhqrRefund, KhqrPayment]:  # fmt: skip
    r.status, r.method, r.refunded_at, r.refunded_by, r.last_error = "refunded", method, clock.now(), actor.id, None
    p.refunded_amount = Decimal(p.refunded_amount or 0) + r.amount
    if p.refunded_amount >= (p.paid_amount or p.amount) and p.status in ("needs_refund", "review", "used"):
        p.status = "refunded"
    add_event(session, OutboxEvent, "khqr.refunded", {
        "khqr_id": str(p.id), "refund_id": str(r.id), "branch_id": str(r.branch_id), "amount": str(r.amount),
        "currency": r.currency, "method": method, "source": r.source, "bank_ref": p.bank_ref,
        "by_role": actor.role, "occurred_at": clock.now().isoformat()})  # fmt: skip
    audit(session, actor, "khqr.refunded", "khqr_refund", r.id, branch_id=r.branch_id,
          after={"amount": str(r.amount), "currency": r.currency, "method": method, "source": r.source,
                 "khqr_id": str(p.id)})  # fmt: skip
    await session.commit()
    return r, p


# ---------------------------------------------------------------- polling and the daily check


async def poll_pending(session: AsyncSession, prov: Provider | None = None) -> int:
    """Pending QRs every run; expired / cancelled ones (late payments) as refresh() allows."""
    settings = get_settings()
    since = clock.now() - timedelta(hours=settings.khqr_late_check_hours)
    rows = list((await session.execute(
        select(KhqrPayment).where((KhqrPayment.status == "pending") | (
            KhqrPayment.status.in_(("expired", "cancelled")) & (KhqrPayment.expires_at >= since)))
        .order_by(KhqrPayment.expires_at).with_for_update(skip_locked=True).limit(50))).scalars())  # fmt: skip
    for p in rows:
        try:
            await refresh(session, p, prov)
        except AppError:
            log.warning("khqr status of %s not known yet", p.id)
    await session.commit()
    return len(rows)


def _ours(p: KhqrPayment) -> dict[str, Any]:
    return {"status": p.status, "amount": str(p.amount), "currency": p.currency,
            "paid_amount": str(p.paid_amount) if p.paid_amount is not None else None,
            "refunded": str(p.refunded_amount or 0)}  # fmt: skip


def compare(p: KhqrPayment, st: Status, open_refunds: Decimal) -> list[tuple[str, dict[str, Any]]]:
    """What does not agree between our row and the provider (pure)."""
    theirs = {"status": st.status, "paid_amount": str(st.paid_amount) if st.paid_amount is not None else None,
              "paid_currency": st.paid_currency, "refunded": str(st.refunded)}  # fmt: skip
    out: list[tuple[str, dict[str, Any]]] = []
    took_money = p.status in ("paid", "used", "review", "needs_refund", "refunded")
    if took_money and st.status != "paid":
        out.append(("not_paid_at_provider", theirs))
    if st.status == "paid" and p.status in ("pending", "expired", "cancelled"):
        out.append(("paid_not_recorded", theirs))
    if st.status == "paid" and p.paid_amount is not None and (
            st.paid_amount != p.paid_amount or (st.paid_currency or p.currency) != (p.paid_currency or p.currency)):  # fmt: skip
        out.append(("amount_mismatch", theirs))
    if p.provider == "payway" and st.refunded != Decimal(p.refunded_amount or 0):
        out.append(("refund_mismatch", theirs))
    if p.status == "paid":
        out.append(("paid_not_used", theirs))  # paid yesterday and no sale took it
    if open_refunds > 0:
        out.append(("refund_open", {**theirs, "open": str(open_refunds)}))
    return out


async def reconcile(session: AsyncSession, day: date, prov: Provider | None = None) -> dict[str, Any]:
    """The QRs created on `day` (Asia/Phnom_Penh) against the provider; issues once per (day, QR, kind).
    One replica at a time (advisory lock); safe to repeat."""
    if not (await session.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": RECONCILE_LOCK})).scalar():
        return {"skipped": "another replica runs it"}
    start = datetime.combine(day, time(0), tzinfo=clock.TIMEZONE)
    query = select(KhqrPayment).where(KhqrPayment.created_at >= start,
                                      KhqrPayment.created_at < start + timedelta(days=1))  # fmt: skip
    if prov is None:  # the fake provider forgets on restart: nothing to compare with
        query = query.where(KhqrPayment.provider != "fake")
    rows = list((await session.execute(query.order_by(KhqrPayment.created_at))).scalars())
    found: dict[str, list[dict[str, Any]]] = {}
    checked = 0
    for p in rows:
        try:
            st = await (prov or provider_for(p)).status(p)
        except AppError as err:
            st = Status(f"unknown ({err.code})")
        checked += 1
        open_refunds = await _open_total(session, p) - Decimal(p.refunded_amount or 0)
        for kind, theirs in compare(p, st, open_refunds):
            exists = (await session.execute(select(KhqrReconcileIssue.id).where(
                KhqrReconcileIssue.run_date == day, KhqrReconcileIssue.khqr_id == p.id,
                KhqrReconcileIssue.kind == kind))).first()  # fmt: skip
            if exists:
                continue
            session.add(KhqrReconcileIssue(run_date=day, branch_id=p.branch_id, khqr_id=p.id, kind=kind,
                                           ours=_ours(p), theirs=theirs))  # fmt: skip
            found.setdefault(str(p.branch_id), []).append({"kind": kind, "khqr_id": str(p.id)})
    for branch_id, issues in found.items():
        kinds: dict[str, int] = {}
        for i in issues:
            kinds[i["kind"]] = kinds.get(i["kind"], 0) + 1
        add_event(session, OutboxEvent, "khqr.reconciled", {"branch_id": branch_id, "date": day.isoformat(),
                                                            "issues": len(issues), "kinds": kinds})  # fmt: skip
    await session.commit()
    return {"date": day.isoformat(), "checked": checked, "issues": sum(len(v) for v in found.values())}


async def list_issues(session: AsyncSession, actor: CurrentUser, day: date | None,
                      branch_id: UUID | None) -> list[KhqrReconcileIssue]:  # fmt: skip
    actor.require("sales.khqr_refund")
    query = select(KhqrReconcileIssue)
    if branch_id is not None:
        actor.require_branch(branch_id)
        query = query.where(KhqrReconcileIssue.branch_id == branch_id)
    elif not actor.is_owner:
        query = query.where(KhqrReconcileIssue.branch_id.in_(actor.branch_ids))
    if day is not None:
        query = query.where(KhqrReconcileIssue.run_date == day)
    rows = await session.execute(query.order_by(KhqrReconcileIssue.run_date.desc(), KhqrReconcileIssue.created_at)
                                 .limit(500))  # fmt: skip
    return list(rows.scalars())


async def by_tran_id(session: AsyncSession, tran_id: str) -> KhqrPayment | None:
    return (await session.execute(select(KhqrPayment).where(KhqrPayment.tran_id == tran_id)
                                  .with_for_update())).scalar_one_or_none()  # fmt: skip


async def run_reconcile_scheduler(db: Any, stop: Any, hour: int = 0, minute: int = 40) -> None:  # noqa: ANN401
    """00:40 Asia/Phnom_Penh (and at start-up): yesterday's QRs against the provider."""
    import asyncio

    while not stop.is_set():
        try:
            async with db.sessionmaker() as session:
                done = await reconcile(session, clock.today() - timedelta(days=1))
            log.info("khqr reconciliation: %s", done)
        except Exception:  # noqa: BLE001 – a failed run must not stop the task
            log.exception("khqr reconciliation failed")
        now_local = datetime.now(clock.TIMEZONE)
        target = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now_local:
            target += timedelta(days=1)
        try:
            await asyncio.wait_for(stop.wait(), timeout=(target - now_local).total_seconds())
        except TimeoutError:
            pass
