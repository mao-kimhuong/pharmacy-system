"""KHQR payments (Bakong or ABA PayWay): create a dynamic QR for the till, ask whether it is paid, give it up,
refund it (owner / branch manager, PIN), the daily check, and PayWay's callback."""

import json
import re
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, requires
from pharmacy_shared.errors import AppError
from pharmacy_shared.idempotency import require_idempotency_key

from ..db import db
from ..models import KhqrPayment
from ..schemas.khqr import (
    CallbackOut,
    CheckoutCreate,
    CheckoutOut,
    KhqrCreate,
    KhqrIssueOut,
    KhqrOut,
    KhqrRefundIn,
    KhqrRefundOut,  # fmt: skip
)
from ..services import khqr
from ..services.clients import Clients, get_clients

router = APIRouter(tags=["KHQR"])

sell = requires("pos.sell")
refunds = requires("sales.khqr_refund")
TRAN_ID = re.compile(r"^[A-Za-z0-9_-]{1,20}$")


def _refund_out(r: Any, p: KhqrPayment) -> KhqrRefundOut:  # noqa: ANN401
    return KhqrRefundOut.model_validate({**{k: getattr(r, k) for k in KhqrRefundOut.model_fields if k != "payment"},
                                         "payment": KhqrOut.model_validate(p)})  # fmt: skip


@router.post("/payments/khqr", response_model=KhqrOut, status_code=201)
async def create(
    body: KhqrCreate, user: CurrentUser = Depends(sell), _: str = Depends(require_idempotency_key),
    session: AsyncSession = Depends(db.session),
) -> KhqrPayment:  # fmt: skip
    """A dynamic KHQR for this amount: ABA PayWay's QR API (KHQR_PROVIDER=payway) or the branch's Bakong account
    (or the shared one). Pay the sale with payments[{method: "KHQR", khqr_id, amount, currency}] once paid."""
    return await khqr.create(session, user, body.model_dump())


@router.post("/payments/payway/checkout", response_model=CheckoutOut, status_code=201)
async def checkout(
    body: CheckoutCreate, user: CurrentUser = Depends(sell), _: str = Depends(require_idempotency_key),
    session: AsyncSession = Depends(db.session),
) -> CheckoutOut:  # fmt: skip
    """PayWay Purchase at the till (cards, ABA PAY, KHQR, wallets on PayWay's hosted page). Post `form.fields` to
    `form.action` as multipart/form-data in a new window; follow GET /payments/khqr/{id} (or PayWay's callback);
    once paid, pay the sale with payments[{method: "PAYWAY", khqr_id, amount, currency}]. Cancel, refunds and the
    daily check as for KHQR."""
    p, form = await khqr.create_checkout(session, user, body.model_dump())
    return CheckoutOut(payment=KhqrOut.model_validate(p), form=form)


@router.get("/payments/khqr/refunds", response_model=list[KhqrRefundOut])
async def list_refunds(
    branch_id: UUID | None = None, status: str | None = Query(default=None, pattern="^(due|requested|refunded)$"),
    user: CurrentUser = Depends(refunds), session: AsyncSession = Depends(db.session),
) -> list[KhqrRefundOut]:  # fmt: skip
    """Money to give back on KHQR payments (failed or cancelled sales, returns, late payments, wrong amounts)."""
    return [_refund_out(r, p) for r, p in await khqr.list_refunds(session, user, branch_id, status)]


@router.post("/payments/khqr/refunds/{refund_id}/refund", response_model=KhqrRefundOut)
async def refund(
    refund_id: UUID, body: KhqrRefundIn, user: CurrentUser = Depends(refunds),
    _: str = Depends(require_idempotency_key), session: AsyncSession = Depends(db.session),
    clients: Clients = Depends(get_clients),
) -> KhqrRefundOut:  # fmt: skip
    """Give the money back (owner, branch manager of the branch; PIN, action sales.khqr_refund). PayWay: the
    refund API, at once; Bakong has no refund API: this records that it was refunded at the bank. Never
    twice: a refunded one comes back as it is."""
    r, p = await khqr.refund(session, user, refund_id, body.pin_token, clients)
    return _refund_out(r, p)


@router.get("/payments/khqr/reconciliation", response_model=list[KhqrIssueOut])
async def reconciliation(
    day: date | None = Query(default=None, alias="date"), branch_id: UUID | None = None,
    user: CurrentUser = Depends(refunds), session: AsyncSession = Depends(db.session),
) -> list:  # fmt: skip
    """What the daily check (00:40 Asia/Phnom_Penh) found: QR payments that do not agree with the provider."""
    return await khqr.list_issues(session, user, day, branch_id)


@router.get("/payments/khqr/{khqr_id}", response_model=KhqrOut)
async def status(
    khqr_id: UUID, request: Request, user: CurrentUser = Depends(sell), session: AsyncSession = Depends(db.session),
) -> KhqrPayment:  # fmt: skip
    """pending / paid / expired / cancelled / used / review / needs_refund / refunded. Asks the provider at most
    every 2 s per QR."""
    p = await khqr.get(session, user, khqr_id, lock=True)
    await khqr.refresh(session, p, redis=request.app.state.redis.client())
    await session.commit()
    return p


@router.post("/payments/khqr/{khqr_id}/cancel", response_model=KhqrOut)
async def cancel(khqr_id: UUID, user: CurrentUser = Depends(sell),
                 session: AsyncSession = Depends(db.session)) -> KhqrPayment:  # fmt: skip
    """Give up a pending QR (closed at PayWay). Already paid → KHQR_STATE; a payment that still arrives later
    becomes a refund due."""
    return await khqr.cancel(session, user, khqr_id)


@router.post("/payments/khqr/{khqr_id}/fake-pay", status_code=204)
async def fake_pay(khqr_id: UUID, user: CurrentUser = Depends(requires("pos.sell")),
                   session: AsyncSession = Depends(db.session)) -> None:  # fmt: skip
    """Development only (KHQR_PROVIDER=fake, never in production; owner): "pay" this QR
    as a customer would, to try the till. 404 everywhere else."""
    from pharmacy_shared.errors import ErrorCode

    from ..config import get_settings

    settings = get_settings()
    if settings.khqr_provider != "fake" or settings.is_production or not user.is_owner:
        raise AppError(ErrorCode.NOT_FOUND, "Not found", status_code=404)
    p = await khqr.get(session, user, khqr_id)
    khqr.FakeProvider.mark_paid(p.md5, p.amount)


@router.post("/payments/payway/callback", response_model=CallbackOut)
async def payway_callback(request: Request, session: AsyncSession = Depends(db.session)) -> CallbackOut:
    """ABA PayWay's pushback after a payment (public: Traefik router sales-payway-callback, rate-limited per IP).
    It is not signed, so nothing in it is believed: only its tran_id is read, and we ask PayWay
    (check-transaction) ourselves. Idempotent; an unknown or malformed tran_id is answered the same way."""
    raw = await request.body()
    try:
        data = json.loads(raw) if raw[:1] in (b"{", b"[") else dict((await request.form()).items())
    except (ValueError, UnicodeDecodeError):
        data = {}
    tran_id = str(data.get("tran_id") or "") if isinstance(data, dict) else ""
    if TRAN_ID.match(tran_id):
        p = await khqr.by_tran_id(session, tran_id)
        if p is not None and p.provider == "payway":
            try:
                await khqr.refresh(session, p, force=True)  # a fresh signal: ask now (Traefik limits per IP)
            except AppError:  # PayWay down: the poller asks again
                pass
            await session.commit()
    return CallbackOut()
