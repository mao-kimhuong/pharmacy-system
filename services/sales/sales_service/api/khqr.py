"""KHQR payments (Bakong): create a dynamic QR for the till, ask whether it is paid."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, requires
from pharmacy_shared.idempotency import require_idempotency_key

from ..db import db
from ..models import KhqrPayment
from ..schemas.khqr import KhqrCreate, KhqrOut
from ..services import khqr

router = APIRouter(tags=["KHQR"])
sell = requires("pos.sell")


@router.post("/payments/khqr", response_model=KhqrOut, status_code=201)
async def create(
    body: KhqrCreate, user: CurrentUser = Depends(sell), _: str = Depends(require_idempotency_key),
    session: AsyncSession = Depends(db.session),
) -> KhqrPayment:  # fmt: skip
    """A dynamic KHQR for this amount on the branch's Bakong account (or the shared one).
    Pay the sale with payments[{method: "KHQR", khqr_id, amount, currency}] once paid."""
    return await khqr.create(session, user, body.model_dump())


@router.get("/payments/khqr/{khqr_id}", response_model=KhqrOut)
async def status(
    khqr_id: UUID, request: Request, user: CurrentUser = Depends(sell), session: AsyncSession = Depends(db.session),
) -> KhqrPayment:  # fmt: skip
    """pending / paid / expired / used / needs_refund. Asks Bakong at most every 2 s per QR."""
    p = await khqr.get(session, user, khqr_id, lock=True)
    await khqr.refresh(session, p, redis=request.app.state.redis.client())
    await session.commit()
    return p


@router.post("/payments/khqr/{khqr_id}/fake-pay", status_code=204)
async def fake_pay(khqr_id: UUID, user: CurrentUser = Depends(requires("pos.sell")),
                   session: AsyncSession = Depends(db.session)) -> None:  # fmt: skip
    """Development only (KHQR_PROVIDER=fake, never in production; owner): "pay" this QR
    as a customer would, to try the till. 404 everywhere else."""
    from pharmacy_shared.errors import AppError, ErrorCode

    from ..config import get_settings

    settings = get_settings()
    if settings.khqr_provider != "fake" or settings.is_production or not user.is_owner:
        raise AppError(ErrorCode.NOT_FOUND, "Not found", status_code=404)
    p = await khqr.get(session, user, khqr_id)
    khqr.FakeProvider.mark_paid(p.md5, p.amount)
