"""The message outbox and the Telegram sender. Rules:

- queue(): one row per message; the dedupe_key is unique, so a job run twice or
  an event delivered twice adds nothing (and a summary already queued or sent is
  never changed).
- No bot token, or no active chat for the target: the message is kept as
  "skipped" (visible in GET /messages), never sent later by surprise.
- Sending: due messages every few seconds (row locks, SKIP LOCKED: one sender at
  a time per message). Telegram 429 → wait its retry_after; other failures
  (network, 5xx) → backoff 30 s × 2^attempts, at most 1 h; after max_attempts →
  failed. A 4xx other than 429 (chat not found, bot blocked) fails at once.
- The token is part of the Bot API URL: it is never logged or stored.
"""

import logging
from datetime import timedelta
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock

from ..config import Settings
from ..models import Message, TelegramChat

log = logging.getLogger(__name__)
MAX_TEXT = 4000  # Telegram allows 4096


async def chat_for(session: AsyncSession, target: str) -> str | None:
    chat = await session.get(TelegramChat, target)
    return chat.chat_id if chat and chat.is_active else None


async def queue(session: AsyncSession, settings: Settings, *, key: str, target: str, kind: str, text: str,
                branch_id: UUID | None = None) -> Message | None:  # fmt: skip
    """Adds the message unless one with this key exists. Returns the new row (None: a duplicate)."""
    chat = await chat_for(session, target)
    status = "queued" if chat and settings.telegram_bot_token else "skipped"
    reason = None if status == "queued" else ("no bot token" if not settings.telegram_bot_token else "no chat set")
    result = await session.execute(insert(Message).values(
        dedupe_key=key[:160], target=target, branch_id=branch_id, chat_id=chat, kind=kind, text=text[:MAX_TEXT],
        status=status, attempts=0, next_attempt_at=clock.now(), last_error=reason,
    ).on_conflict_do_nothing().returning(Message.id))  # fmt: skip
    new_id = result.scalar_one_or_none()
    return await session.get(Message, new_id) if new_id else None


class Sender:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self.transport = transport

    async def _post(self, chat_id: str, text: str) -> tuple[int, dict[str, Any]]:
        url = f"{self.settings.telegram_api_base}/bot{self.settings.telegram_bot_token}/sendMessage"
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5), transport=self.transport) as client:
            r = await client.post(url, json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True})
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {}

    async def send(self, session: AsyncSession, m: Message) -> None:
        """One attempt; updates the row (the caller commits)."""
        m.attempts += 1
        try:
            status, body = await self._post(m.chat_id or "", m.text)
        except httpx.HTTPError as exc:
            status, body = 0, {"description": exc.__class__.__name__}
        if status == 200 and body.get("ok"):
            m.status, m.sent_at, m.last_error = "sent", clock.now(), None
            return
        m.last_error = f"{status} {body.get('description') or ''}".strip()[:300]
        if 400 <= status < 500 and status != 429:
            m.status = "failed"  # wrong chat, bot blocked: retrying will not help
            return
        if m.attempts >= self.settings.max_attempts:
            m.status = "failed"
            return
        retry_after = int((body.get("parameters") or {}).get("retry_after") or 0)
        wait = retry_after if status == 429 and retry_after else min(30 * 2 ** (m.attempts - 1), 3600)
        m.next_attempt_at = clock.now() + timedelta(seconds=wait)

    async def send_due(self, session: AsyncSession, limit: int = 20) -> int:
        rows = (await session.execute(select(Message).where(
            Message.status == "queued", Message.next_attempt_at <= clock.now())
            .order_by(Message.next_attempt_at).limit(limit).with_for_update(skip_locked=True))).scalars().all()  # fmt: skip
        for m in rows:
            await self.send(session, m)
        await session.commit()
        if rows:
            log.info("telegram: %d message(s) tried", len(rows))
        return len(rows)
