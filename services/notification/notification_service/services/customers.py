"""Customer Telegram messages (T2 phase 1). Only to a linked chat, only with the
customer's consent for the topic, in the customer's language, never 21:00–07:00
(telegram.queue holds them). One message per event (dedupe key).

| Message | Topic | From |
| --- | --- | --- |
| receipt (A4 invoice PDF) | receipts | invoice.created |
| return refund | receipts | invoice.returned (the newest return with money back) |
| deposit taken / refunded / kept as credit | receipts | deposit.taken, deposit.settled |
| order ready (what is left to pay) | orders | sale_order.ready |
| order status (clinic groups only) | orders | sale_order.ordered / updated / cancelled / closed |
| refill reminder | reminders | rx.supply → job at 09:00, N days before it runs out |
| balance (statement PDF) | balance | job: the 1st of the month; overdue: once per oldest due date |
| promotion | marketing | POST /campaigns, at most 2 a month per customer |

Texts come from customer_texts (allow-listed values only).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.audit import record_audit
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.internal import InternalClient

from ..config import Settings
from ..models import (
    BranchPrefs,
    Campaign,
    KnownBranch,
    KnownCustomer,
    KnownCustomerGroup,
    Message,
    OutboxEvent,
    RefillReminder,
    TelegramLink,
)
from . import customer_texts as ct
from . import links
from .telegram import queue

CUSTOMER_EVENTS = {"customer.created", "customer.updated", "customer.activated", "customer.deactivated"}
GROUP_EVENTS = {"customer_group.created", "customer_group.updated", "customer_group.activated",
                "customer_group.deactivated"}  # fmt: skip
ROUTING_KEYS = ("customer.*", "customer_group.*", "deposit.*", "sale_order.*", "rx.supply", "invoice.returned")
STATUS_EVENTS = {"sale_order.ordered", "sale_order.updated", "sale_order.cancelled", "sale_order.closed"}


def _tail(phone: str | None) -> str:
    return f"…{phone[-4:]}" if phone else "…"


async def _target(session: AsyncSession, customer_id: Any, topic: str) -> KnownCustomer | None:
    """The customer when linked, active and allowing this topic; else None (nothing is queued)."""
    if not customer_id:
        return None
    cid = UUID(str(customer_id))
    customer = await session.get(KnownCustomer, cid)
    if customer is None or not customer.is_active or not await links.active_links(session, "customer", cid):
        return None
    return customer if await links.allowed(session, cid, topic) else None


async def _branch(session: AsyncSession, branch_id: Any, lang: str) -> str:
    b = await session.get(KnownBranch, UUID(str(branch_id))) if branch_id else None
    return ct.branch_name({"code": b.code, "name_en": b.name_en, "name_km": b.name_km} if b else None, lang)


async def _send(session: AsyncSession, settings: Settings, customer: KnownCustomer, *, key: str, kind: str, text: str,
                summary: str, branch_id: Any = None, document: dict[str, Any] | None = None) -> Message | None:  # fmt: skip
    return await queue(session, settings, key=key, target=f"customer:{customer.id}", kind=kind, text=text,
                       branch_id=UUID(str(branch_id)) if branch_id else None, subject_id=customer.id,
                       summary=f"{summary} → customer {_tail(customer.phone)}", document=document)  # fmt: skip


async def handle(session: AsyncSession, settings: Settings, event_type: str, p: dict[str, Any]) -> bool:
    """True when the event was one of these."""
    if event_type in CUSTOMER_EVENTS:
        values = {"id": UUID(p["customer_id"]), "phone": p.get("phone") or "",
                  "preferred_lang": p.get("preferred_lang") or "km",
                  "group_id": UUID(p["group_id"]) if p.get("group_id") else None, "is_active": bool(p.get("is_active", True))}  # fmt: skip
        await session.execute(insert(KnownCustomer).values(**values).on_conflict_do_update(
            index_elements=["id"], set_={k: v for k, v in values.items() if k != "id"}))  # fmt: skip
    elif event_type in GROUP_EVENTS:
        await session.execute(insert(KnownCustomerGroup).values(id=UUID(p["group_id"]), is_clinic=bool(p.get("is_clinic")))
                              .on_conflict_do_update(index_elements=["id"], set_={"is_clinic": bool(p.get("is_clinic"))}))  # fmt: skip
    elif event_type == "branch.settings_updated":
        values = {"branch_id": UUID(p["branch_id"]), "refill_reminder_days": int(p.get("refill_reminder_days") or 3),
                  "opening_hours": p.get("opening_hours")}  # fmt: skip
        await session.execute(insert(BranchPrefs).values(**values).on_conflict_do_update(
            index_elements=["branch_id"], set_={k: v for k, v in values.items() if k != "branch_id"}))  # fmt: skip
    elif event_type == "invoice.created":
        await _receipt(session, settings, p)
    elif event_type == "invoice.returned":
        await _return_refund(session, settings, p)
    elif event_type in ("deposit.taken", "deposit.settled"):
        await _deposit(session, settings, event_type, p)
    elif event_type == "sale_order.ready":
        await _order_ready(session, settings, p)
    elif event_type in STATUS_EVENTS:
        await _order_status(session, settings, p)
    elif event_type == "rx.supply":
        await supply(session, p)
    else:
        return False
    return True


async def _receipt(session: AsyncSession, settings: Settings, inv: dict[str, Any]) -> None:
    c = await _target(session, (inv.get("customer") or {}).get("id"), "receipts")
    if c is None or not inv.get("number"):
        return
    lang = c.preferred_lang
    branch = ct.branch_name(inv.get("branch"), lang)
    await _send(session, settings, c, key=f"receipt:{inv['invoice_id']}", kind="receipt",
                text=ct.receipt(lang, branch, inv["number"], inv.get("total"), inv.get("total_khr")),
                summary=f"Receipt {inv['number']}", branch_id=(inv.get("branch") or {}).get("id"),
                document={"type": "invoice_a4", "id": inv["invoice_id"], "lang": lang})  # fmt: skip


async def _return_refund(session: AsyncSession, settings: Settings, inv: dict[str, Any]) -> None:
    returns = sorted(inv.get("returns") or [], key=lambda r: r.get("created_at") or "")
    if not returns:
        return
    r = returns[-1]
    if Decimal(str(r.get("refund_usd") or 0)) <= 0:
        return
    c = await _target(session, (inv.get("customer") or {}).get("id"), "receipts")
    if c is None:
        return
    branch = ct.branch_name(inv.get("branch"), c.preferred_lang)
    await _send(session, settings, c, key=f"refund:{r['return_id']}", kind="refund",
                text=ct.return_refund(c.preferred_lang, branch, r.get("number") or "", r["refund_usd"],
                                      r.get("refund_method") or ""),
                summary=f"Refund {r.get('number')}", branch_id=(inv.get("branch") or {}).get("id"))  # fmt: skip


async def _deposit(session: AsyncSession, settings: Settings, event_type: str, d: dict[str, Any]) -> None:
    c = await _target(session, d.get("customer_id"), "receipts")
    if c is None:
        return
    lang = c.preferred_lang
    branch = await _branch(session, d.get("branch_id"), lang)
    order = d.get("document_no") or ""
    if event_type == "deposit.taken":
        text, kind, what = ct.deposit_taken(lang, branch, order, d.get("amount")), "deposit", "Deposit"
    elif d.get("status") == "refunded":
        left = Decimal(str(d.get("amount") or 0)) - Decimal(str(d.get("used") or 0))
        text, kind, what = ct.deposit_refunded(lang, branch, order, left), "refund", "Deposit refund"
    elif d.get("status") == "credit":
        text, kind, what = ct.deposit_credit(lang, branch, order, d.get("remaining")), "deposit", "Deposit as credit"
    else:
        return
    await _send(session, settings, c, key=f"{event_type}:{d['deposit_id']}:{d.get('status')}", kind=kind, text=text,
                summary=f"{what} {order}", branch_id=d.get("branch_id"))  # fmt: skip


async def _order_ready(session: AsyncSession, settings: Settings, o: dict[str, Any]) -> None:
    c = await _target(session, (o.get("customer") or {}).get("id"), "orders")
    if c is None:
        return
    branch = ct.branch_name(o.get("branch"), c.preferred_lang)
    await _send(session, settings, c, key=f"ready:{o['sale_order_id']}:{o.get('ready_at')}", kind="order_ready",
                text=ct.order_ready(c.preferred_lang, branch, o["number"], o.get("remaining_usd")),
                summary=f"Order {o['number']} ready", branch_id=(o.get("branch") or {}).get("id"))  # fmt: skip


async def _order_status(session: AsyncSession, settings: Settings, o: dict[str, Any]) -> None:
    """Clinics (customer group is_clinic) follow their orders; other customers only get "ready"."""
    c = await _target(session, (o.get("customer") or {}).get("id"), "orders")
    if c is None or c.group_id is None:
        return
    group = await session.get(KnownCustomerGroup, c.group_id)
    if group is None or not group.is_clinic or o.get("status") not in ct.ORDER_STATUS:
        return
    branch = ct.branch_name(o.get("branch"), c.preferred_lang)
    await _send(session, settings, c, key=f"status:{o['sale_order_id']}:{o['status']}", kind="order_status",
                text=ct.order_status(c.preferred_lang, branch, o["number"], o["status"]),
                summary=f"Order {o['number']} {o['status']}", branch_id=(o.get("branch") or {}).get("id"))  # fmt: skip


# ------------------------------------------------------------------ refill reminders


async def supply(session: AsyncSession, p: dict[str, Any]) -> None:
    """Keeps the newest supply per Rx item. qty 0 from the same invoice (cancelled, all returned): gone."""
    item = UUID(p["rx_item_id"])
    row = await session.get(RefillReminder, item, with_for_update=True)
    version = int(p.get("invoice_version") or 0)
    same = row is not None and str(row.invoice_id) == str(p["invoice_id"])
    if same and version <= row.invoice_version:
        return  # an older or repeated version of the invoice we have
    if not p.get("supply_days") or not p.get("customer_id"):
        if same:
            await session.delete(row)
        return
    dispensed = date.fromisoformat(p["dispensed_on"])
    if row is not None and not same and dispensed < row.dispensed_on:
        return  # an older sale of this item: the newer supply decides
    prefs = await session.get(BranchPrefs, UUID(p["branch_id"]))
    days = prefs.refill_reminder_days if prefs else 3
    runs_out = date.fromisoformat(p["runs_out_on"])
    values = {"invoice_id": UUID(p["invoice_id"]), "invoice_version": version, "customer_id": UUID(p["customer_id"]),
              "branch_id": UUID(p["branch_id"]), "prescription_number": p.get("prescription_number") or "",
              "medicine_name": (p.get("medicine_name") or "")[:200], "refills_left": bool(p.get("refills_left")),
              "dispensed_on": dispensed, "runs_out_on": runs_out,
              "remind_on": date.fromordinal(max(dispensed.toordinal() + 1, runs_out.toordinal() - days))}  # fmt: skip
    await session.execute(insert(RefillReminder).values(rx_item_id=item, **values, sent_at=None).on_conflict_do_update(
        index_elements=["rx_item_id"], set_={**values, "sent_at": None}))  # fmt: skip


REFILL_LOCK, BALANCE_LOCK = 7_202_683, 7_202_684


async def _lock(session: AsyncSession, key: int) -> bool:
    return bool((await session.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": key})).scalar_one())


async def refill_job(session: AsyncSession, settings: Settings, today: date) -> int | None:
    if not await _lock(session, REFILL_LOCK):
        return None
    rows = (await session.execute(select(RefillReminder).where(
        RefillReminder.remind_on <= today, RefillReminder.runs_out_on >= today, RefillReminder.sent_at.is_(None))
        .with_for_update(skip_locked=True))).scalars().all()  # fmt: skip
    made = 0
    for r in rows:
        r.sent_at = clock.now()
        c = await _target(session, r.customer_id, "reminders")
        if c is None:
            continue
        names = await links.allowed(session, c.id, "show_medicine_names")
        branch = await _branch(session, r.branch_id, c.preferred_lang)
        made += bool(await _send(
            session, settings, c, key=f"refill:{r.rx_item_id}:{r.invoice_id}", kind="refill",
            text=ct.refill(c.preferred_lang, branch, r.prescription_number, r.runs_out_on, r.refills_left,
                           r.medicine_name if names else None),
            summary=f"Refill reminder {r.prescription_number}", branch_id=r.branch_id))  # fmt: skip
    await session.commit()
    return made


# ------------------------------------------------------------------ balance reminders


async def balance_job(session: AsyncSession, settings: Settings, customers: InternalClient, today: date) -> int | None:
    """The 1st of the month: everyone linked with a balance > 0. Every day: overdue debts, once per oldest due
    date. With the statement PDF (rendered when sent)."""
    if not await _lock(session, BALANCE_LOCK):
        return None
    ids = (await session.execute(select(TelegramLink.subject_id).where(
        TelegramLink.role == "customer", TelegramLink.unlinked_at.is_(None)).distinct())).scalars().all()  # fmt: skip
    made = 0
    for cid in ids:
        c = await _target(session, cid, "balance")
        if c is None:
            continue
        credit = await customers.get(f"/customers/{cid}/credit")
        bal, overdue = Decimal(str(credit.get("balance") or 0)), Decimal(str(credit.get("overdue") or 0))
        doc = {"type": "customer_statement", "id": str(cid), "lang": c.preferred_lang}
        if overdue > 0 and credit.get("oldest_due_on"):
            made += bool(await _send(session, settings, c, key=f"overdue:{cid}:{credit['oldest_due_on']}",
                                     kind="overdue", summary=f"Overdue {overdue} USD", document=doc,
                                     text=ct.balance(c.preferred_lang, bal, overdue, credit["oldest_due_on"], True)))  # fmt: skip
        elif today.day == 1 and bal > 0:
            made += bool(await _send(session, settings, c, key=f"balance:{cid}:{today:%Y-%m}", kind="balance",
                                     summary=f"Balance {bal} USD", document=doc,
                                     text=ct.balance(c.preferred_lang, bal, overdue, None, False)))  # fmt: skip
    await session.commit()
    return made


# ------------------------------------------------------------------ promotions


async def marketing_this_month(session: AsyncSession, customer_id: UUID, now: datetime) -> int:
    local = now.astimezone(clock.TIMEZONE)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return (await session.execute(select(func.count()).select_from(Message).where(
        Message.chat_role == "customer", Message.subject_id == customer_id, Message.kind == "marketing",
        Message.created_at >= start))).scalar_one()  # fmt: skip


async def send_campaign(session: AsyncSession, settings: Settings, actor: CurrentUser, data: dict[str, Any]) -> Campaign:
    actor.require("notifications.customers")
    if not data["text_km"].strip() or not data["text_en"].strip():
        raise AppError(ErrorCode.VALIDATION_ERROR, "Write the promotion in Khmer and English", status_code=422)
    camp = Campaign(title=data["title"].strip(), text_km=data["text_km"].strip(), text_en=data["text_en"].strip(),
                    promotion_id=data.get("promotion_id"), created_by=actor.id, created_at=clock.now())  # fmt: skip
    session.add(camp)
    await session.flush()
    ids = (await session.execute(select(TelegramLink.subject_id).where(
        TelegramLink.role == "customer", TelegramLink.unlinked_at.is_(None)).distinct())).scalars().all()  # fmt: skip
    for cid in ids:
        c = await _target(session, cid, "marketing")
        if c is None:
            continue
        if await marketing_this_month(session, cid, clock.now()) >= settings.marketing_per_month:
            camp.over_cap += 1
            continue
        if await _send(session, settings, c, key=f"campaign:{camp.id}:{cid}", kind="marketing",
                       text=ct.marketing(c.preferred_lang, camp.text_km, camp.text_en), summary=f"Promotion {camp.title}"):  # fmt: skip
            camp.queued += 1
            await session.flush()  # the next customer's count sees it
    record_audit(session, OutboxEvent, service="notification", action="telegram.campaign_sent", entity_type="campaign",
                 entity_id=camp.id, actor=actor, after={"title": camp.title, "queued": camp.queued,
                                                        "over_cap": camp.over_cap})  # fmt: skip
    await session.commit()
    return camp
