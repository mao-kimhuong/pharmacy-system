"""T2 customer Telegram (Customer detail), promotions, and the bot webhook."""

import hmac
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, current_user, requires
from pharmacy_shared.errors import AppError, ErrorCode

from ..db import db
from ..schemas.telegram import (
    CampaignIn,
    CampaignOut,
    ConsentsIn,
    CustomerTelegramOut,
    LinkTokenOut,
    WebhookOk,
)
from ..services import bot, customer_admin, customers
from .router import get_sender

router = APIRouter(tags=["telegram customers"])
public = APIRouter(tags=["telegram bot"])


@router.get("/customers/{customer_id}/telegram", response_model=CustomerTelegramOut)
async def customer_telegram(customer_id: UUID, request: Request, user: CurrentUser = Depends(current_user),
                            session: AsyncSession = Depends(db.session)) -> dict:  # fmt: skip
    """Linked or not, and each consent with when and where it changed (notifications.customers or
    contacts.customers)."""
    return await customer_admin.status(session, request.app.state.settings, user, customer_id)


@router.post("/customers/{customer_id}/telegram/link-token", response_model=LinkTokenOut)
async def customer_link_token(customer_id: UUID, request: Request,
                              user: CurrentUser = Depends(requires("notifications.customers")),
                              session: AsyncSession = Depends(db.session)) -> dict:  # fmt: skip
    """A t.me link for a QR shown at the counter (7 days, once; no phone check: staff see who scans it)."""
    return await customer_admin.counter_token(session, request.app.state.settings, user, customer_id)


@router.post("/customers/{customer_id}/telegram/unlink", response_model=CustomerTelegramOut)
async def customer_unlink(customer_id: UUID, request: Request,
                          user: CurrentUser = Depends(requires("notifications.customers")),
                          session: AsyncSession = Depends(db.session)) -> dict:  # fmt: skip
    """Ends the link (the customer asked at the counter); all consents go off."""
    await customer_admin.unlink(session, user, customer_id)
    return await customer_admin.status(session, request.app.state.settings, user, customer_id)


@router.put("/customers/{customer_id}/telegram/consents", response_model=CustomerTelegramOut)
async def customer_consents(customer_id: UUID, body: ConsentsIn, request: Request,
                            user: CurrentUser = Depends(requires("notifications.customers")),
                            session: AsyncSession = Depends(db.session)) -> dict:  # fmt: skip
    """What the customer asked for at the counter. Promotions: only the customer turns them on (403)."""
    await customer_admin.set_consents(session, user, customer_id, dict(body.consents))
    return await customer_admin.status(session, request.app.state.settings, user, customer_id)


@router.post("/campaigns", response_model=CampaignOut, status_code=201)
async def campaign(body: CampaignIn, request: Request, user: CurrentUser = Depends(requires("notifications.customers")),
                   session: AsyncSession = Depends(db.session)) -> object:  # fmt: skip
    """A promotion to every linked customer who allows promotions, at most 2 a month each (the others are
    counted in over_cap). Sent 07:00–21:00 only."""
    return await customers.send_campaign(session, request.app.state.settings, user, body.model_dump())


@public.post("/telegram/webhook", response_model=WebhookOk)
async def webhook(request: Request, session: AsyncSession = Depends(db.session),
                  x_telegram_bot_api_secret_token: str | None = Header(default=None)) -> dict:  # fmt: skip
    """Telegram's updates. The secret token (set with setWebhook) must match TELEGRAM_WEBHOOK_SECRET; without
    one configured every call is refused. Each update is handled once."""
    settings = request.app.state.settings
    expected = settings.telegram_webhook_secret
    if not expected or not hmac.compare_digest((x_telegram_bot_api_secret_token or "").encode(), expected.encode()):
        raise AppError(ErrorCode.NOT_AUTHENTICATED, "Not Telegram", status_code=401)
    update = await request.json()
    if not isinstance(update, dict):
        return {"ok": True}
    sender = get_sender(request)
    made = await bot.handle_update(session, settings, sender, update, bot.HOOKS)
    await session.commit()
    await bot.send_now(session, sender, made)
    return {"ok": True}
