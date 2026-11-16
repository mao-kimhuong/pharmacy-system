"""T2: My profile → Telegram (any signed-in user links their own Telegram, for approval buttons and commands)."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, current_user

from ..db import db
from ..models import LinkToken, Staff
from ..schemas.telegram import LinkTokenOut, MyTelegramOut, SupplierLinkIn, SupplierTelegramOut, UnlinkIn
from ..services import links, suppliers

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


@router.get("/suppliers/{supplier_id}/telegram", response_model=SupplierTelegramOut)
async def supplier_telegram(supplier_id: UUID, request: Request, user: CurrentUser = Depends(current_user),
                            session: AsyncSession = Depends(db.session)) -> dict:  # fmt: skip
    """The supplier's linked chats (purchasing.order or contacts.suppliers)."""
    return await suppliers.status(session, request.app.state.settings, user, supplier_id)


@router.post("/suppliers/{supplier_id}/telegram/link-token", response_model=LinkTokenOut)
async def supplier_link_token(supplier_id: UUID, body: SupplierLinkIn, request: Request,
                              user: CurrentUser = Depends(current_user),
                              session: AsyncSession = Depends(db.session)) -> dict:  # fmt: skip
    """A t.me link for one contact of the supplier (purchasing.order; 7 days, once; a private or group chat).
    Sent POs then go there as a PDF with a "Received / Confirmed" button."""
    return await suppliers.link_token(session, request.app.state.settings, user, supplier_id, body.label)


@router.post("/suppliers/{supplier_id}/telegram/unlink", response_model=SupplierTelegramOut)
async def supplier_unlink(supplier_id: UUID, body: UnlinkIn, request: Request, user: CurrentUser = Depends(current_user),
                          session: AsyncSession = Depends(db.session)) -> dict:  # fmt: skip
    await suppliers.unlink(session, user, supplier_id, body.link_id)
    return await suppliers.status(session, request.app.state.settings, user, supplier_id)


@router.post("/me/telegram/unlink", response_model=MyTelegramOut)
async def my_unlink(request: Request, user: CurrentUser = Depends(current_user),
                    session: AsyncSession = Depends(db.session)) -> dict:  # fmt: skip
    await links.unlink_subject(session, "staff", user.id, user)
    await session.commit()
    return await _status(session, request, user)
