"""/internal/v1 of the sales service (service token; never through Traefik)."""

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.approvals import VIA_TELEGRAM, DecideIn, acting_user
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.internal import InternalCaller, internal_caller

from ..config import get_settings
from ..db import db
from ..models import KhqrPayment
from ..schemas.preview import CartPreviewOut, InternalPreviewIn
from ..services import discount_approvals
from ..services.clients import Clients, get_clients
from ..services.preview import preview

router = APIRouter()


@router.post("/carts/preview", response_model=CartPreviewOut, response_model_exclude_none=True)
async def cart_preview(
    body: InternalPreviewIn, caller: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session), clients: Clients = Depends(get_clients),
) -> dict:  # fmt: skip
    """The catalog's promotion preview: prices only matter, so the cart is checked as
    an owner pharmacist would see it (no cost: the draft's author may not see cost)."""
    actor = CurrentUser(id=caller.user_id or uuid4(), role="owner", branch_ids=frozenset(), is_pharmacist=True,
                        permissions=frozenset({"pos.sell", "pos.dispense_rx", "controlled.dispense"}))  # fmt: skip
    return await preview(session, actor, clients, body.cart.model_dump(), body.draft_promotion)


@router.post("/khqr/fake/{khqr_id}/pay", status_code=204)
async def fake_pay(
    khqr_id: UUID, caller: InternalCaller = Depends(internal_caller), session: AsyncSession = Depends(db.session),
) -> None:  # fmt: skip
    """Development and tests only (KHQR_PROVIDER=fake): the customer "pays" this QR."""
    from ..services.khqr import FakeProvider

    settings = get_settings()
    if settings.khqr_provider != "fake" or settings.is_production:
        raise AppError(ErrorCode.NOT_FOUND, "Not found", status_code=404)
    p = await session.get(KhqrPayment, khqr_id)
    if p is None:
        raise AppError(ErrorCode.NOT_FOUND, "KHQR payment not found", status_code=404)
    FakeProvider.mark_paid(p.md5, p.amount)


@router.post("/discount-approvals/{approval_id}/decide")
async def decide_discount(approval_id: UUID, body: DecideIn, caller: InternalCaller = Depends(internal_caller),
                          session: AsyncSession = Depends(db.session)) -> dict:  # fmt: skip
    """T2: a manager / the owner approved or rejected on Telegram (the same rules as their PIN at the till)."""
    a = await discount_approvals.decide(session, acting_user(body.actor), approval_id, body.decision, VIA_TELEGRAM)
    return {"status": a.status}
