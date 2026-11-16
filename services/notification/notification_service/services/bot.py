"""Telegram updates (webhook or polling), handled once each (update_id). Rules:

- /start <token>: links the chat (links.py). A printed customer token first asks
  for the customer's own phone number (Telegram's contact button) and links only
  when it matches. Customer and staff links: private chats only.
- /stop: unlinks everything of this chat; a customer's consents all go off.
- /settings (customers): one button per topic; a tap turns it on or off (logged).
- Unknown chats get the greeting at most – never data. Group chats that are not a
  registered owner/branch chat are ignored.
- Replies are messages in the outbox (kind bot_reply to "chat:<id>"); the webhook
  sends them right after the update is stored. Button taps get their popup at once
  (answerCallbackQuery, not a message).
Later phases hook in here: approval buttons (ap:), bot commands.
"""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..models import TOPICS, KnownCustomer, Message, PendingLink, TelegramChat, TelegramUpdate
from . import customer_texts as ct
from . import links
from .telegram import Sender, queue

log = logging.getLogger(__name__)
REMOVE_KEYBOARD = {"remove_keyboard": True}
HOOKS: Any = None  # staff commands and approval buttons (staff_bot.Hooks), set at import of main


class Reply:
    """Collects the replies of one update (dedupe key update:<id>:<n>)."""

    def __init__(self, session: AsyncSession, settings: Settings, update_id: int, chat_id: str) -> None:
        self.session, self.settings, self.update_id, self.chat_id = session, settings, update_id, chat_id
        self.made: list[Message] = []

    async def __call__(self, text: str, kind: str = "bot_reply", *, markup: dict[str, Any] | None = None,
                       edit: str | None = None, chat_id: str | None = None) -> None:  # fmt: skip
        chat = chat_id or self.chat_id
        m = await queue(self.session, self.settings, key=f"update:{self.update_id}:{len(self.made)}",
                        target=f"chat:{chat}", kind=kind, text=text, reply_markup=markup,
                        method="edit" if edit else "send", edit_message_id=edit)  # fmt: skip
        if m:
            self.made.append(m)


async def _is_group_chat(session: AsyncSession, chat_id: str) -> TelegramChat | None:
    return (await session.execute(select(TelegramChat).where(TelegramChat.chat_id == chat_id,
                                                             TelegramChat.is_active.is_(True)))).scalars().first()  # fmt: skip


async def _customer_of_chat(session: AsyncSession, chat_id: str) -> KnownCustomer | None:
    for link in await links.links_of_chat(session, chat_id):
        if link.role == "customer":
            return await session.get(KnownCustomer, link.subject_id) or KnownCustomer(id=link.subject_id)
    return None


async def handle_update(session: AsyncSession, settings: Settings, sender: Sender, update: dict[str, Any],
                        hooks: Any = None) -> list[Message]:  # fmt: skip
    """Stores the update id (a repeat does nothing) and queues the replies. The caller commits and sends."""
    update_id = int(update.get("update_id") or 0)
    new = (await session.execute(insert(TelegramUpdate).values(update_id=update_id)
                                 .on_conflict_do_nothing().returning(TelegramUpdate.update_id))).scalar_one_or_none()  # fmt: skip
    if new is None:
        return []
    if cb := update.get("callback_query"):
        msg = cb.get("message") or {}
        reply = Reply(session, settings, update_id, str((msg.get("chat") or {}).get("id") or ""))
        await _on_callback(session, settings, sender, cb, reply, hooks)
        return reply.made
    msg = update.get("message") or {}
    chat = msg.get("chat") or {}
    if not chat.get("id"):
        return []
    reply = Reply(session, settings, update_id, str(chat["id"]))
    await _on_message(session, settings, msg, reply, hooks)
    return reply.made


async def _on_message(session: AsyncSession, settings: Settings, msg: dict[str, Any], reply: Reply, hooks: Any) -> None:
    chat, sender_user = msg["chat"], msg.get("from") or {}
    chat_id, user_id = str(chat["id"]), str(sender_user.get("id") or "")
    private = chat.get("type") == "private"
    if contact := msg.get("contact"):
        if private:
            await _on_contact(session, contact, chat_id, user_id, reply)
        return
    text = (msg.get("text") or "").strip()
    if not text.startswith("/"):
        if private and not await links.links_of_chat(session, chat_id):
            await reply(ct.HELLO)
        return
    command, _, arg = text.partition(" ")
    command = command.split("@")[0].lower()
    if command == "/start":
        await _on_start(session, settings, arg.strip(), chat_id, user_id, private, reply)
    elif command == "/stop":
        n = await links.unlink_chat(session, chat_id, "customer")
        if n or private:
            await reply(ct.STOPPED if n else ct.NOT_LINKED, markup=REMOVE_KEYBOARD)
    elif command == "/settings" and (customer := await _customer_of_chat(session, chat_id)):
        await _send_settings(session, customer, reply)
    elif hooks is not None and await hooks.command(session, settings, command, arg.strip(), chat_id, user_id,
                                                   private, reply):  # fmt: skip
        return  # staff commands (phase 3)
    elif command == "/help" and (customer := await _customer_of_chat(session, chat_id)):
        await reply(ct.customer_help(customer.preferred_lang))
    elif private and not await links.links_of_chat(session, chat_id):
        await reply(ct.HELLO)


async def _on_start(session: AsyncSession, settings: Settings, token_text: str, chat_id: str, user_id: str,
                    private: bool, reply: Reply) -> None:  # fmt: skip
    if not token_text:
        if private:
            await reply(ct.HELLO)
        return
    token = await links.find_token(session, token_text)
    if token is None:
        if private:
            await reply(ct.TOKEN_BAD)
        return
    if token.role in ("customer", "staff") and not private:
        await reply(ct.GROUP_NO_LINK)
        return
    if token.role == "customer" and token.phone_check:
        await links.remember_pending(session, chat_id, token)
        await reply(ct.SHARE_PHONE, markup={"keyboard": [[{"text": ct.SHARE_BUTTON, "request_contact": True}]],
                                            "one_time_keyboard": True, "resize_keyboard": True})  # fmt: skip
        return
    await _link_and_greet(session, token, chat_id, user_id, reply)


async def _link_and_greet(session: AsyncSession, token: Any, chat_id: str, user_id: str, reply: Reply) -> None:
    role, label = token.role, token.label
    row = await links.link(session, token, chat_id, user_id)
    lang = "km"
    if role == "customer":
        customer = await session.get(KnownCustomer, row.subject_id)
        lang = customer.preferred_lang if customer else "km"
    await reply(ct.linked(lang, role, label), markup=REMOVE_KEYBOARD)


async def _on_contact(session: AsyncSession, contact: dict[str, Any], chat_id: str, user_id: str, reply: Reply) -> None:
    token = await links.pending_token(session, chat_id)
    if token is None:
        await reply(ct.TOKEN_BAD, markup=REMOVE_KEYBOARD)
        return
    if str(contact.get("user_id") or "") != user_id:  # someone else's contact card proves nothing
        await reply(ct.NOT_YOUR_CONTACT)
        return
    customer = await session.get(KnownCustomer, token.subject_id)
    if not links.phone_matches(customer, contact.get("phone_number") or ""):
        pending = await session.get(PendingLink, chat_id)
        pending.token_hash = ""  # this chat may not try again with the same token
        await reply(ct.PHONE_MISMATCH, markup=REMOVE_KEYBOARD)
        return
    await _link_and_greet(session, token, chat_id, user_id, reply)


async def _send_settings(session: AsyncSession, customer: KnownCustomer, reply: Reply, edit: str | None = None) -> None:
    current = {t: c.granted for t, c in (await links.consents_of(session, customer.id)).items()}
    lang = customer.preferred_lang or "km"
    await reply(ct.settings_text(lang), markup=ct.settings_markup(lang, current), edit=edit)


async def _on_callback(session: AsyncSession, settings: Settings, sender: Sender, cb: dict[str, Any], reply: Reply,
                       hooks: Any) -> None:  # fmt: skip
    data = str(cb.get("data") or "")
    msg = cb.get("message") or {}
    message_id = str(msg.get("message_id") or "")
    if data.startswith("cs:"):
        customer = await _customer_of_chat(session, reply.chat_id)
        if customer is None:
            await sender.answer_callback(cb.get("id") or "", "Not linked / មិនទាន់ភ្ជាប់")
            return
        topic = data[3:]
        if topic == "stop":
            await links.unlink_chat(session, reply.chat_id, "customer")
            await reply(ct.STOPPED, edit=message_id)
            await sender.answer_callback(cb.get("id") or "", "OK")
            return
        if topic not in TOPICS:
            return
        on = await links.allowed(session, customer.id, topic)
        await links.set_consents(session, customer.id, {topic: not on}, "bot_settings", None)
        await _send_settings(session, customer, reply, edit=message_id)
        await sender.answer_callback(cb.get("id") or "", "✅" if not on else "⬜")
        return
    if hooks is not None:
        await hooks.callback(session, settings, sender, cb, reply)


async def send_now(session: AsyncSession, sender: Sender, made: list[Message]) -> None:
    """After the update's transaction: try its replies at once (else the sender loop does)."""
    for m in made:
        row = await session.get(Message, m.id, with_for_update=True, populate_existing=True)
        if row and row.status == "queued":
            await sender.send(session, row)
    await session.commit()
