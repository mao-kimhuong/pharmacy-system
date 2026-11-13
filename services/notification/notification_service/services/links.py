"""Linking Telegram chats to records (T2) and customer consent. Rules:

- Tokens go in t.me/<bot>?start=<token>. Only their SHA-256 is stored; each is used
  once. Printed tokens (receipt, statement) and supplier tokens last 7 days, staff
  tokens (My profile) 15 minutes. Token = HMAC of (role, ref, record, expiry): a
  reprinted receipt shows the same QR; after it is used or expired the next print
  gets a new one.
- A printed token can be photographed, so it links only after the customer shares
  their Telegram phone number (Telegram's contact button, their own contact) and it
  matches the customer's phone. A mismatch links nothing: the counter links them
  (a token shown by staff, no phone check).
- Linking works in private chats only. A customer or supplier chat is linked to one
  record; linking a customer again replaces the older chat. Staff link their own
  Telegram user (approvals and commands are matched by the Telegram user id).
- Consent per customer + topic with date and source. Start turns on receipts,
  reminders, balance and orders (the customer asked for the bot); medicine names
  in reminders and marketing stay off until chosen. /stop unlinks and turns
  everything off. Every change: User Log.
"""

import hashlib
import hmac
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.audit import record_audit
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.phone import normalize_phone

from ..config import Settings
from ..models import (
    DEFAULT_ON,
    TOPICS,
    CustomerConsent,
    KnownCustomer,
    LinkToken,
    OutboxEvent,
    PendingLink,
    TelegramLink,
)

PREFIX = {"customer": "c", "staff": "s", "supplier": "p"}


def _key(settings: Settings) -> bytes:
    secret = settings.telegram_link_secret or f"telegram-link:{settings.service_token}"
    return secret.encode()


def make_token(settings: Settings, role: str, ref: str, subject_id: UUID, expires_at: datetime) -> str:
    mac = hmac.new(_key(settings), f"{role}|{ref}|{subject_id}|{expires_at.isoformat()}".encode(), hashlib.sha256)
    return PREFIX[role] + mac.hexdigest()[:40]  # Telegram's start payload: ≤ 64 of [A-Za-z0-9_-]


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def deep_link(settings: Settings, token: str) -> str | None:
    return f"https://t.me/{settings.telegram_bot_username}?start={token}" if settings.telegram_bot_username else None


async def issue(session: AsyncSession, settings: Settings, *, role: str, subject_id: UUID, ref: str, via: str,
                phone_check: bool, label: str = "", created_by: UUID | None = None) -> str:  # fmt: skip
    """The token for (role, ref): the same while unused and unexpired, a new one otherwise. The caller commits."""
    now = clock.now()
    row = (await session.execute(select(LinkToken).where(LinkToken.role == role, LinkToken.ref == ref)
                                 .with_for_update())).scalar_one_or_none()  # fmt: skip
    if row and row.used_at is None and row.expires_at > now and row.subject_id == subject_id:
        return make_token(settings, role, ref, subject_id, row.expires_at)
    life = timedelta(minutes=settings.staff_link_minutes) if role == "staff" else timedelta(days=settings.link_token_days)
    expires = (now + life).replace(microsecond=0)
    token = make_token(settings, role, ref, subject_id, expires)
    if row:
        await session.delete(row)
        await session.flush()
    session.add(LinkToken(token_hash=token_hash(token), role=role, subject_id=subject_id, ref=ref, via=via,
                          phone_check=phone_check, label=label, expires_at=expires, created_by=created_by))  # fmt: skip
    await session.flush()
    return token


async def find_token(session: AsyncSession, token: str, *, lock: bool = True) -> LinkToken | None:
    """Unused and unexpired, else None."""
    q = select(LinkToken).where(LinkToken.token_hash == token_hash(token))
    row = (await session.execute(q.with_for_update() if lock else q)).scalar_one_or_none()
    if row is None or row.used_at is not None or row.expires_at <= clock.now():
        return None
    return row


async def active_links(session: AsyncSession, role: str, subject_id: UUID) -> list[TelegramLink]:
    return list((await session.execute(select(TelegramLink).where(
        TelegramLink.role == role, TelegramLink.subject_id == subject_id, TelegramLink.unlinked_at.is_(None))
        .order_by(TelegramLink.linked_at))).scalars())  # fmt: skip


async def links_of_chat(session: AsyncSession, chat_id: str) -> list[TelegramLink]:
    return list((await session.execute(select(TelegramLink).where(
        TelegramLink.chat_id == chat_id, TelegramLink.unlinked_at.is_(None)))).scalars())  # fmt: skip


async def staff_link_of_user(session: AsyncSession, tg_user_id: str) -> TelegramLink | None:
    return (await session.execute(select(TelegramLink).where(
        TelegramLink.role == "staff", TelegramLink.tg_user_id == tg_user_id, TelegramLink.unlinked_at.is_(None))
        .order_by(TelegramLink.linked_at.desc()).limit(1))).scalar_one_or_none()  # fmt: skip


def _audit(session: AsyncSession, action: str, role: str, subject_id: UUID, actor: CurrentUser | None,
           after: dict[str, Any], before: dict[str, Any] | None = None) -> None:  # fmt: skip
    record_audit(session, OutboxEvent, service="notification", action=action, entity_type=role,
                 entity_id=str(subject_id), actor=actor, before=before or {}, after=after)  # fmt: skip


async def link(session: AsyncSession, token: LinkToken, chat_id: str, tg_user_id: str) -> TelegramLink:
    """Uses the token and links the chat (the caller commits)."""
    now = clock.now()
    token.used_at = now
    if token.role in ("customer", "staff"):  # one chat per customer, one Telegram user per staff account
        await session.execute(update(TelegramLink).where(
            TelegramLink.role == token.role, TelegramLink.subject_id == token.subject_id,
            TelegramLink.unlinked_at.is_(None)).values(unlinked_at=now, unlinked_by="relinked"))  # fmt: skip
    if token.role == "customer":  # and a chat belongs to one customer
        await session.execute(update(TelegramLink).where(
            TelegramLink.role == "customer", TelegramLink.chat_id == chat_id,
            TelegramLink.unlinked_at.is_(None)).values(unlinked_at=now, unlinked_by="relinked"))  # fmt: skip
    else:
        await session.execute(update(TelegramLink).where(
            TelegramLink.role == token.role, TelegramLink.subject_id == token.subject_id,
            TelegramLink.chat_id == chat_id, TelegramLink.unlinked_at.is_(None))
            .values(unlinked_at=now, unlinked_by="relinked"))  # fmt: skip
    row = TelegramLink(role=token.role, subject_id=token.subject_id, chat_id=chat_id, tg_user_id=tg_user_id,
                       label=token.label, via=token.via, linked_at=now)  # fmt: skip
    session.add(row)
    await session.execute(update(PendingLink).where(PendingLink.chat_id == chat_id).values(token_hash=""))
    if token.role == "customer":
        await set_consents(session, token.subject_id, {t: True for t in DEFAULT_ON}, "bot_start", None,
                           only_missing=True)  # fmt: skip
    _audit(session, f"telegram.{token.role}_linked", token.role, token.subject_id, None,
           {"via": token.via, "label": token.label})  # fmt: skip
    await session.flush()
    return row


def phone_matches(customer: KnownCustomer | None, shared_phone: str) -> bool:
    if customer is None or not customer.phone:
        return False
    try:
        return normalize_phone(shared_phone) == normalize_phone(customer.phone)
    except ValueError:
        return False


async def unlink_chat(session: AsyncSession, chat_id: str, by: str, actor: CurrentUser | None = None) -> int:
    """/stop: every link of this chat ends; customers' consents all go off."""
    rows = await links_of_chat(session, chat_id)
    for r in rows:
        r.unlinked_at, r.unlinked_by = clock.now(), by
        if r.role == "customer":
            await set_consents(session, r.subject_id, {t: False for t in TOPICS}, "bot_stop", None)
        _audit(session, f"telegram.{r.role}_unlinked", r.role, r.subject_id, actor, {"by": by})
    return len(rows)


async def unlink_subject(session: AsyncSession, role: str, subject_id: UUID, actor: CurrentUser,
                         link_id: UUID | None = None) -> int:  # fmt: skip
    rows = [r for r in await active_links(session, role, subject_id) if link_id is None or r.id == link_id]
    for r in rows:
        r.unlinked_at, r.unlinked_by = clock.now(), str(actor.id)
        _audit(session, f"telegram.{role}_unlinked", role, subject_id, actor, {"by": "staff", "label": r.label})
    if role == "customer" and rows:
        await set_consents(session, subject_id, {t: False for t in TOPICS}, "staff", actor)
    return len(rows)


async def consents_of(session: AsyncSession, customer_id: UUID) -> dict[str, CustomerConsent]:
    rows = (await session.execute(select(CustomerConsent).where(CustomerConsent.customer_id == customer_id))).scalars()
    return {r.topic: r for r in rows}


async def allowed(session: AsyncSession, customer_id: UUID, topic: str) -> bool:
    row = await session.get(CustomerConsent, (customer_id, topic))
    return bool(row and row.granted)


async def set_consents(session: AsyncSession, customer_id: UUID, wanted: dict[str, bool], source: str,
                       actor: CurrentUser | None, only_missing: bool = False) -> dict[str, bool]:  # fmt: skip
    """Changes the given topics; returns what changed. Logged (customer's own changes: no actor)."""
    current = await consents_of(session, customer_id)
    before, after = {}, {}
    for topic, granted in wanted.items():
        if topic not in TOPICS:
            continue
        row = current.get(topic)
        if row is not None and (only_missing or row.granted == granted):
            continue
        before[topic] = row.granted if row else None
        after[topic] = granted
        if row is None:
            session.add(CustomerConsent(customer_id=customer_id, topic=topic, granted=granted, source=source,
                                        changed_at=clock.now(), changed_by=actor.id if actor else None))  # fmt: skip
        else:
            row.granted, row.source, row.changed_at = granted, source, clock.now()
            row.changed_by = actor.id if actor else None
    if after:
        _audit(session, "telegram.consent_changed", "customer", customer_id, actor, {**after, "source": source},
               before)  # fmt: skip
        await session.flush()
    return after


async def remember_pending(session: AsyncSession, chat_id: str, token: LinkToken) -> None:
    row = await session.get(PendingLink, chat_id)
    if row is None:
        session.add(PendingLink(chat_id=chat_id, token_hash=token.token_hash, created_at=clock.now()))
    else:
        row.token_hash, row.created_at = token.token_hash, clock.now()


async def pending_token(session: AsyncSession, chat_id: str) -> LinkToken | None:
    row = await session.get(PendingLink, chat_id)
    if row is None or not row.token_hash:
        return None
    token = (await session.execute(select(LinkToken).where(LinkToken.token_hash == row.token_hash)
                                   .with_for_update())).scalar_one_or_none()  # fmt: skip
    if token is None or token.used_at is not None or token.expires_at <= clock.now():
        return None
    return token
