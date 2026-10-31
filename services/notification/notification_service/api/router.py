"""Telegram: chats, test message, message status, alert settings. Mounted under
/api/notifications/v1. Permission notifications.manage (owner; managers for
their own branches)."""

from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser, requires
from pharmacy_shared.internal import InternalClient

from ..db import db
from ..schemas.telegram import ChatIn, ChatOut, MessageOut, SettingsIn, SettingsOut, TestIn
from ..services import admin
from ..services.telegram import Sender

router = APIRouter(tags=["telegram"])
manage = requires("notifications.manage")


def get_sender(request: Request) -> Sender:
    return Sender(request.app.state.settings, getattr(request.app.state, "telegram_transport", None))


def get_reports(request: Request) -> InternalClient:
    s = request.app.state.settings
    return getattr(request.app.state, "reports_client", None) or InternalClient(
        s.reports_url, s.service_name, s.service_token, read_timeout=30)  # fmt: skip


@router.get("/chats", response_model=list[ChatOut])
async def chats(user: CurrentUser = Depends(manage), session: AsyncSession = Depends(db.session)) -> list:
    return await admin.list_chats(session, user)


@router.put("/chats/{target}", response_model=ChatOut)
async def set_chat(target: str, body: ChatIn, user: CurrentUser = Depends(manage),
                   session: AsyncSession = Depends(db.session)) -> object:  # fmt: skip
    """target: "owner" (owner only) or a branch id (its chat)."""
    return await admin.set_chat(session, user, target, body.model_dump())


@router.post("/test", response_model=MessageOut)
async def test(body: TestIn, request: Request, user: CurrentUser = Depends(manage),
               session: AsyncSession = Depends(db.session), sender: Sender = Depends(get_sender)) -> object:  # fmt: skip
    """Sends a test message now. No TELEGRAM_BOT_TOKEN: 503 TELEGRAM_NOT_CONFIGURED (kept as skipped)."""
    return await admin.send_test(session, user, request.app.state.settings, sender, body.target)


@router.get("/messages", response_model=list[MessageOut])
async def messages(status: str | None = None, kind: str | None = None, limit: int = Query(default=100, ge=1, le=500),
                   user: CurrentUser = Depends(manage), session: AsyncSession = Depends(db.session)) -> list:  # fmt: skip
    return await admin.list_messages(session, user, status, kind, limit)


@router.get("/settings", response_model=SettingsOut)
async def get_settings(user: CurrentUser = Depends(manage), session: AsyncSession = Depends(db.session)) -> object:
    row = await admin.get_settings_row(session)
    await session.commit()
    return row


@router.put("/settings", response_model=SettingsOut)
async def put_settings(body: SettingsIn, user: CurrentUser = Depends(manage),
                       session: AsyncSession = Depends(db.session)) -> object:  # fmt: skip
    return await admin.set_settings(session, user, body.model_dump())


@router.post("/daily-summary/run")
async def run_summary(request: Request, day: date | None = None, user: CurrentUser = Depends(manage),
                      session: AsyncSession = Depends(db.session),
                      reports: InternalClient = Depends(get_reports)) -> dict:  # fmt: skip
    """Owner: queue the 20:00 summary now (what the job does). Run twice: nothing new."""
    queued = await admin.run_summary(session, user, request.app.state.settings, reports, day or clock.today())
    return {"queued": queued}
