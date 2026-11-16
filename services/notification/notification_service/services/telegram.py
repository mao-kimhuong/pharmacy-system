"""The message outbox and the Telegram sender. Rules:

- queue(): one row per message; the dedupe_key is unique, so a job run twice or
  an event delivered twice adds nothing (and a summary already queued or sent is
  never changed).
- One bot, chat roles (T2): owner and branch group chats (telegram_chats),
  customer / supplier chats and staff users (telegram_links), and "reply" (an
  answer in the chat a command or button came from). Each message kind is allowed
  only for some roles (ROLE_KINDS); anything else is refused before it is stored.
- No bot token, or no active chat for the target: the message is kept as
  "skipped" (visible in GET /messages), never sent later by surprise.
- Quiet hours: customer messages are not sent 21:00–07:00 (Asia/Phnom_Penh); they
  wait until 07:00 (checked when queued and again before sending). Answers to the
  customer's own commands are not held back.
- Customer and supplier rows: the message log shows only `summary`; the text is
  blanked once the message is sent or has failed for good.
- Sending: due messages every few seconds (row locks, SKIP LOCKED: one sender at
  a time per message). Telegram 429 → wait its retry_after; other failures
  (network, 5xx, a PDF not ready yet) → backoff 30 s × 2^attempts, at most 1 h;
  after max_attempts → failed. A 4xx other than 429 (chat not found, bot blocked)
  fails at once.
- PDFs (receipt, statement, PO) are rendered by the document service when sent
  and never stored here.
- The token is part of the Bot API URL: it is never logged or stored.
"""

import base64
import json
import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.errors import AppError
from pharmacy_shared.internal import InternalClient

from ..config import Settings
from ..models import Message, TelegramChat, TelegramLink

log = logging.getLogger(__name__)
MAX_TEXT = 4000  # Telegram allows 4096
MAX_CAPTION = 1000  # a document's caption: 1024

_GROUP = {"daily_summary", "stock_digest", "lockout", "controlled", "khqr_refund", "recall", "below_cost",
          "large_discount", "test", "approval", "ops", "sensor"}  # fmt: skip
CUSTOMER_KINDS = {"receipt", "refill", "order_ready", "order_status", "balance", "overdue", "deposit", "refund",
                  "marketing", "invoice"}  # fmt: skip
ROLE_KINDS: dict[str, set[str]] = {
    "owner": _GROUP | {"security"},
    "branch": _GROUP,
    "customer": CUSTOMER_KINDS,
    "staff": {"approval", "linked"},
    "supplier": {"purchase_order", "linked"},
    "reply": {"bot_reply", "approval_done", "command_reply"},
}
PRIVATE_ROLES = ("customer", "supplier")  # the log shows the summary only


class NotAllowed(ValueError):
    """A message kind sent to a chat role that may not get it (a bug, never data)."""


def role_of(target: str) -> str:
    if target == "owner":
        return "owner"
    kind, _, _ = target.partition(":")
    if kind in ("customer", "staff", "supplier"):
        return kind
    if kind == "chat":
        return "reply"
    UUID(target)  # a branch id (ValueError otherwise)
    return "branch"


def check_kind(role: str, kind: str) -> None:
    if kind not in ROLE_KINDS.get(role, set()):
        raise NotAllowed(f"{kind} messages may not go to {role} chats")


async def chat_for(session: AsyncSession, target: str) -> str | None:
    """The chat a target's messages go to (None: not set / not linked)."""
    role = role_of(target)
    if role in ("owner", "branch"):
        chat = await session.get(TelegramChat, target)
        return chat.chat_id if chat and chat.is_active else None
    if role == "reply":
        return target.partition(":")[2]
    subject = UUID(target.partition(":")[2])
    link = (await session.execute(select(TelegramLink).where(
        TelegramLink.role == role, TelegramLink.subject_id == subject, TelegramLink.unlinked_at.is_(None))
        .order_by(TelegramLink.linked_at.desc()).limit(1))).scalar_one_or_none()  # fmt: skip
    return link.chat_id if link else None


def quiet_until(now: datetime, settings: Settings) -> datetime | None:
    """The next 07:00 Phnom Penh when `now` is in the quiet hours, else None."""
    local = now.astimezone(clock.TIMEZONE)
    start, end = settings.quiet_from_hour, settings.quiet_until_hour
    quiet = local.hour >= start or local.hour < end
    if not quiet:
        return None
    day = local.date() if local.hour < end else local.date() + timedelta(days=1)
    return datetime(day.year, day.month, day.day, end, tzinfo=clock.TIMEZONE)


async def queue(session: AsyncSession, settings: Settings, *, key: str, target: str, kind: str, text: str,
                branch_id: UUID | None = None, chat_id: str | None = None, subject_id: UUID | None = None,
                summary: str = "", document: dict[str, Any] | None = None, reply_markup: dict[str, Any] | None = None,
                method: str = "send", edit_message_id: str | None = None) -> Message | None:  # fmt: skip
    """Adds the message unless one with this key exists. Returns the new row (None: a duplicate).
    chat_id: a known chat of the target (a supplier with several chats); else the target's chat."""
    role = role_of(target)
    check_kind(role, kind)
    chat = chat_id or await chat_for(session, target)
    status = "queued" if chat and settings.telegram_bot_token else "skipped"
    reason = None if status == "queued" else ("no bot token" if not settings.telegram_bot_token else "no chat set")
    due = clock.now()
    if role == "customer" and (later := quiet_until(due, settings)):
        due = later
    if role in ("customer", "supplier", "staff") and subject_id is None:
        subject_id = UUID(target.partition(":")[2])
    result = await session.execute(insert(Message).values(
        dedupe_key=key[:160], target=target, branch_id=branch_id, chat_id=chat, kind=kind,
        text=text[:MAX_CAPTION if document else MAX_TEXT], status=status, attempts=0, next_attempt_at=due,
        last_error=reason, chat_role=role, subject_id=subject_id, summary=summary[:200], document=document,
        reply_markup=reply_markup, method=method, edit_message_id=edit_message_id,
    ).on_conflict_do_nothing().returning(Message.id))  # fmt: skip
    new_id = result.scalar_one_or_none()
    return await session.get(Message, new_id) if new_id else None


def _finish(m: Message, status: str) -> None:
    m.status = status
    if m.chat_role in PRIVATE_ROLES:
        m.text = ""  # the log keeps the summary only


class Sender:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None,
                 documents: InternalClient | None = None) -> None:  # fmt: skip
        self.settings = settings
        self.transport = transport
        self.documents = documents or InternalClient(settings.document_url, settings.service_name,
                                                     settings.service_token, read_timeout=30)  # fmt: skip

    def _url(self, method: str) -> str:
        return f"{self.settings.telegram_api_base}/bot{self.settings.telegram_bot_token}/{method}"

    async def call(self, method: str, payload: dict[str, Any] | None = None,
                   files: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:  # fmt: skip
        """One Bot API call (also used for getUpdates, answerCallbackQuery, setWebhook)."""
        async with httpx.AsyncClient(timeout=httpx.Timeout(35, connect=5), transport=self.transport) as client:
            if files:
                data = {k: (json.dumps(v) if isinstance(v, dict) else str(v)) for k, v in (payload or {}).items()}
                r = await client.post(self._url(method), data=data, files=files)
            else:
                r = await client.post(self._url(method), json=payload or {})
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {}

    async def _pdf(self, doc: dict[str, Any]) -> tuple[str, bytes]:
        out = await self.documents.post("/render", doc)
        return out["filename"], base64.b64decode(out["pdf_base64"])

    async def _deliver(self, m: Message) -> tuple[int, dict[str, Any]]:
        markup = {"reply_markup": m.reply_markup} if m.reply_markup is not None else {}
        if m.method == "edit":
            return await self.call("editMessageText", {"chat_id": m.chat_id, "message_id": m.edit_message_id,
                                                       "text": m.text, **markup})  # fmt: skip
        if m.method == "caption":  # a document's text is its caption
            return await self.call("editMessageCaption", {"chat_id": m.chat_id, "message_id": m.edit_message_id,
                                                          "caption": m.text, **markup})  # fmt: skip
        if m.document:
            name, pdf = await self._pdf(m.document)
            return await self.call("sendDocument", {"chat_id": m.chat_id, "caption": m.text, **markup},
                                   files={"document": (name, pdf, "application/pdf")})  # fmt: skip
        return await self.call("sendMessage", {"chat_id": m.chat_id, "text": m.text,
                                               "disable_web_page_preview": True, **markup})  # fmt: skip

    async def send(self, session: AsyncSession, m: Message) -> None:
        """One attempt; updates the row (the caller commits)."""
        if m.chat_role == "customer" and (later := quiet_until(clock.now(), self.settings)):
            m.next_attempt_at = later  # a retry that fell into the night waits; no attempt counted
            return
        m.attempts += 1
        try:
            status, body = await self._deliver(m)
        except httpx.HTTPError as exc:
            status, body = 0, {"description": exc.__class__.__name__}
        except AppError as exc:  # the PDF could not be made yet (document not ready / unavailable)
            status, body = 0, {"description": f"document: {exc.code}"}
        description = str(body.get("description") or "")
        if (status == 200 and body.get("ok")) or (m.method != "send" and "message is not modified" in description):
            result = body.get("result") if isinstance(body.get("result"), dict) else {}
            if result.get("message_id"):
                m.tg_message_id = str(result["message_id"])
            m.sent_at, m.last_error = clock.now(), None
            _finish(m, "sent")
            return
        m.last_error = f"{status} {description}".strip()[:300]
        if 400 <= status < 500 and status != 429:
            _finish(m, "failed")  # wrong chat, bot blocked: retrying will not help
            return
        if m.attempts >= self.settings.max_attempts:
            _finish(m, "failed")
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

    async def answer_callback(self, callback_id: str, text: str, alert: bool = False) -> None:
        """The small popup after a button tap: must come within seconds, so not through the outbox (it is
        not a message). Best effort."""
        if not self.settings.telegram_bot_token:
            return
        try:
            await self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:190],
                                                    "show_alert": alert})  # fmt: skip
        except httpx.HTTPError:
            log.warning("telegram: answerCallbackQuery failed")
