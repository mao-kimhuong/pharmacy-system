"""Chats, settings, the test message and the message list (notifications.manage).
The owner sets every chat and the owner's own; a manager only their branches'."""

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.audit import record_audit
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.internal import InternalClient

from ..config import Settings
from ..models import AlertSettings, Message, OutboxEvent, TelegramChat
from . import jobs
from .telegram import Sender, queue


def check_target(user: CurrentUser, target: str) -> UUID | None:
    if target == "owner":
        if not user.is_owner:
            raise AppError(ErrorCode.FORBIDDEN, "Only the owner sets the owner's chat", status_code=403)
        return None
    try:
        branch = UUID(target)
    except ValueError as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, 'target: "owner" or a branch id', status_code=422) from exc
    user.require_branch(branch)
    return branch


async def list_chats(session: AsyncSession, user: CurrentUser) -> list[TelegramChat]:
    rows = (await session.execute(select(TelegramChat).order_by(TelegramChat.target))).scalars().all()
    return [c for c in rows if user.is_owner or (c.target != "owner" and user.can_access_branch(UUID(c.target)))]


async def set_chat(session: AsyncSession, user: CurrentUser, target: str, data: dict[str, Any]) -> TelegramChat:
    branch = check_target(user, target)
    chat = await session.get(TelegramChat, target)
    before = {"chat_id": chat.chat_id, "is_active": chat.is_active} if chat else {}
    if chat is None:
        chat = TelegramChat(target=target)
        session.add(chat)
    chat.chat_id, chat.is_active, chat.updated_by = data["chat_id"], data["is_active"], user.id
    record_audit(session, OutboxEvent, service="notification", action="telegram_chat.set", entity_type="telegram_chat",
                 entity_id=target, actor=user, branch_id=branch, before=before,
                 after={"chat_id": chat.chat_id, "is_active": chat.is_active})  # fmt: skip
    await session.commit()
    await session.refresh(chat)  # updated_at is set by the database: load it here, not lazily in the response
    return chat


async def send_test(session: AsyncSession, user: CurrentUser, settings: Settings, sender: Sender, target: str) -> Message:
    """Queued and tried at once. Without a bot token: kept as skipped, 503."""
    branch = check_target(user, target)
    m = await queue(session, settings, key=f"test:{target}:{clock.now().isoformat()}", target=target, kind="test",
                    text=f"✅ Test message from the pharmacy system ({clock.now().astimezone(clock.TIMEZONE):%Y-%m-%d %H:%M}).",
                    branch_id=branch)  # fmt: skip
    await session.commit()
    if not settings.telegram_bot_token:
        raise AppError(ErrorCode.TELEGRAM_NOT_CONFIGURED, "TELEGRAM_BOT_TOKEN is not set: nothing can be sent",
                       status_code=503, details={"message_id": str(m.id) if m else None})  # fmt: skip
    if m.status == "skipped":
        raise AppError(ErrorCode.VALIDATION_ERROR, f"No active chat for {target}: set it first", status_code=422)
    await sender.send(session, m)
    await session.commit()
    return m


async def list_messages(session: AsyncSession, user: CurrentUser, status: str | None, kind: str | None,
                        limit: int) -> list[Message]:  # fmt: skip
    q = select(Message)
    if not user.is_owner:
        q = q.where(Message.branch_id.in_(list(user.branch_ids) or [UUID(int=0)]), Message.target != "owner")
    if status:
        q = q.where(Message.status == status)
    if kind:
        q = q.where(Message.kind == kind)
    return list((await session.execute(q.order_by(Message.created_at.desc()).limit(limit))).scalars())


async def get_settings_row(session: AsyncSession) -> AlertSettings:
    row = await session.get(AlertSettings, 1)
    if row is None:
        row = AlertSettings(id=1)
        session.add(row)
        await session.flush()
    return row


async def set_settings(session: AsyncSession, user: CurrentUser, data: dict[str, Any]) -> AlertSettings:
    if not user.is_owner:
        raise AppError(ErrorCode.FORBIDDEN, "Only the owner sets the alert thresholds", status_code=403)
    row = await get_settings_row(session)
    before = {"large_discount_pct": str(row.large_discount_pct), "large_discount_usd": str(row.large_discount_usd)}
    row.large_discount_pct, row.large_discount_usd, row.updated_by = (data["large_discount_pct"],
                                                                      data["large_discount_usd"], user.id)  # fmt: skip
    record_audit(session, OutboxEvent, service="notification", action="alert_settings.updated", entity_type="settings",
                 entity_id="1", actor=user, before=before,
                 after={k: str(v) for k, v in data.items()})  # fmt: skip
    await session.commit()
    return row


async def run_summary(session: AsyncSession, user: CurrentUser, settings: Settings, reports: InternalClient,
                      day: date) -> int:  # fmt: skip
    if not user.is_owner:
        raise AppError(ErrorCode.FORBIDDEN, "Only the owner runs the daily summary by hand", status_code=403)
    return await jobs.daily_summary(session, settings, reports, day) or 0
