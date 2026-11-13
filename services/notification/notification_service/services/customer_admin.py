"""Customer detail → Telegram (staff side). Seeing it: notifications.customers or
contacts.customers; changing it (counter link, unlink, consents): notifications.customers.
Staff may turn any topic off and on, except marketing: only the customer turns that
on (in the bot), staff can only turn it off. Every change: User Log."""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode

from ..config import Settings
from ..models import TOPICS, KnownCustomer, LinkToken
from . import links

VIEW = ("notifications.customers", "contacts.customers")


def _view(user: CurrentUser) -> None:
    if not user.has_any(*VIEW):
        user.require("notifications.customers")


async def status(session: AsyncSession, settings: Settings, user: CurrentUser, customer_id: UUID) -> dict[str, Any]:
    _view(user)
    rows = await links.active_links(session, "customer", customer_id)
    consents = await links.consents_of(session, customer_id)
    return {
        "customer_id": customer_id, "linked": bool(rows),
        "links": [{"id": r.id, "via": r.via, "label": r.label, "linked_at": r.linked_at} for r in rows],
        "consents": [{"topic": t, "granted": bool(consents[t].granted) if t in consents else False,
                      "source": consents[t].source if t in consents else None,
                      "changed_at": consents[t].changed_at if t in consents else None} for t in TOPICS],
        "bot_configured": bool(settings.telegram_bot_token and settings.telegram_bot_username),
    }  # fmt: skip


async def counter_token(session: AsyncSession, settings: Settings, user: CurrentUser, customer_id: UUID) -> dict[str, Any]:
    """A QR the customer scans at the counter in front of staff: no phone check (staff saw who it is)."""
    user.require("notifications.customers")
    customer = await session.get(KnownCustomer, customer_id)
    if customer is None or not customer.is_active:
        raise AppError(ErrorCode.NOT_FOUND, "Customer not found or deactivated", status_code=404)
    token = await links.issue(session, settings, role="customer", subject_id=customer_id, ref=f"counter:{customer_id}",
                              via="counter", phone_check=False, created_by=user.id)  # fmt: skip
    row = await session.get(LinkToken, links.token_hash(token))
    await session.commit()
    return {"url": links.deep_link(settings, token), "expires_at": row.expires_at}


async def unlink(session: AsyncSession, user: CurrentUser, customer_id: UUID) -> int:
    user.require("notifications.customers")
    n = await links.unlink_subject(session, "customer", customer_id, user)
    await session.commit()
    return n


async def set_consents(session: AsyncSession, user: CurrentUser, customer_id: UUID, wanted: dict[str, bool]) -> None:
    user.require("notifications.customers")
    if wanted.get("marketing"):
        raise AppError(ErrorCode.FORBIDDEN, "Only the customer can turn promotions on (in the bot)", status_code=403,
                       details={"field": "marketing", "reason": "customer_only"})  # fmt: skip
    await links.set_consents(session, customer_id, wanted, "staff", user)
    await session.commit()


async def internal_link(session: AsyncSession, settings: Settings, data: dict[str, Any]) -> str | None:
    """For receipts and statements (document service): a printed token, or None."""
    if not (settings.telegram_bot_username and settings.telegram_bot_token):
        return None
    cid = data["customer_id"]
    customer = await session.get(KnownCustomer, cid)
    if customer is None or not customer.is_active or await links.active_links(session, "customer", cid):
        return None
    token = await links.issue(session, settings, role="customer", subject_id=cid, ref=data["ref"], via=data["via"],
                              phone_check=True)  # fmt: skip
    await session.commit()
    return links.deep_link(settings, token)
