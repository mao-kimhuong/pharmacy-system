"""T2: My profile → Telegram (any signed-in user links their own Telegram, for approval buttons and commands)."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, current_user

from ..db import db
from ..models import LinkToken, Staff
from ..schemas.telegram import LinkTokenOut, MyTelegramOut
from ..services import links

router = APIRouter(tags=["telegram staff"])


async def _status(session: AsyncSession, request: Request, user: CurrentUser) -> dict:
    rows = await links.active_links(session, "staff", user.id)
    s = request.app.state.settings
    return {"linked": bool(rows), "linked_at": rows[-1].linked_at if rows else None,
            "bot_configured": bool(s.telegram_bot_token and s.telegram_bot_username),
            "can_approve": user.has("notifications.approve_via_telegram")}  # fmt: skip


@router.get("/me/telegram", response_model=MyTelegramOut)
async def my_telegram(request: Request, user: CurrentUser = Depends(current_user),
                      session: AsyncSession = Depends(db.session)) -> dict:  # fmt: skip
    return await _status(session, request, user)


@router.post("/me/telegram/link-token", response_model=LinkTokenOut)
async def my_link_token(request: Request, user: CurrentUser = Depends(current_user),
                        session: AsyncSession = Depends(db.session)) -> dict:  # fmt: skip
    """A t.me link for your own Telegram (15 minutes, once). Open it on your phone and press Start."""
    settings = request.app.state.settings
    staff = await session.get(Staff, user.id)
    token = await links.issue(session, settings, role="staff", subject_id=user.id, ref=f"profile:{user.id}",
                              via="profile", phone_check=False, label=staff.name if staff else "", created_by=user.id)  # fmt: skip
    row = await session.get(LinkToken, links.token_hash(token))
    await session.commit()
    return {"url": links.deep_link(settings, token), "expires_at": row.expires_at}


@router.post("/me/telegram/unlink", response_model=MyTelegramOut)
async def my_unlink(request: Request, user: CurrentUser = Depends(current_user),
                    session: AsyncSession = Depends(db.session)) -> dict:  # fmt: skip
    await links.unlink_subject(session, "staff", user.id, user)
    await session.commit()
    return await _status(session, request, user)
