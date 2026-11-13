"""T2 phase 2: approval buttons in the branch's and the owner's Telegram chats. Rules:

- Shrinkage (pending), stock take (in review), transfer request (to the source branch), purchase request and a
  discount above the seller's cap (asked from the till) each send one message to the branch's chat and the
  owner's (only the owner's when only the owner may decide), with ✅ / ❌ buttons when Telegram may decide it:
  not controlled, no PIN needed, the value known and ≤ the owner's limit (telegram_approval_max_usd, 100). Else the
  message says why and to open the app. Stock values (cost) show only in the owner's chat; a discount amount
  shows in both.
- A tap counts only from a linked staff Telegram user (staff_link: My profile) whose CURRENT access (auth
  /internal/v1/users/{id}/access) has notifications.approve_via_telegram, the kind's permission and the branch;
  the limits are checked again. Otherwise "not allowed" and nothing changes.
- The owning service then decides as that user with its own rules (pharmacy_shared.approvals) and logs it with
  "via": "telegram". Only the first decision counts: the approval row is locked, and a second tap (or a decision
  in the app first: the service answers 409) only shows who decided.
- Every message of the approval is then edited: who decided and when, buttons gone (a message not sent yet goes
  out already decided). Decided in the app → the same edit from the service's event.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.approvals import Actor, acting_user
from pharmacy_shared.errors import AppError
from pharmacy_shared.internal import InternalClient

from ..config import Settings
from ..models import AlertSettings, Approval, KnownBranch, Message, Staff
from . import links, texts
from .telegram import Sender, queue

log = logging.getLogger(__name__)
TELEGRAM_PERMISSION = "notifications.approve_via_telegram"
DEFAULT_LIMIT = Decimal("100")


@dataclass(frozen=True)
class Kind:
    permission: str
    service: str
    path: str
    can_reject: bool
    cost: bool  # the value is a stock cost: the owner's chat only
    page: str


KINDS = {
    "shrinkage": Kind("inventory.shrinkage_approve", "inventory", "/shrinkages/{id}/decide", True, True, "/approvals"),
    "count": Kind("stockcount.approve", "stockcount", "/counts/{id}/decide", False, True, "/approvals"),
    "transfer_request": Kind("transfers.approve", "inventory", "/transfer-requests/{id}/decide", True, True,
                             "/approvals"),
    "purchase_request": Kind("purchasing.request_approve", "purchasing", "/purchase-requests/{id}/decide", True, True,
                             "/approvals"),
    "discount": Kind("sales.discount", "sales", "/discount-approvals/{id}/decide", True, False, "/pos"),
}  # fmt: skip
ROUTING_KEYS = ("shrinkage.*", "count.*", "transfer_request.*", "purchase_request.*", "discount_approval.*")

Clients = Callable[[str], Any]  # service name → client with get / post (InternalClient)


def default_clients(settings: Settings) -> Clients:
    urls = {"auth": settings.auth_url, "inventory": settings.inventory_url, "stockcount": settings.stockcount_url,
            "purchasing": settings.purchasing_url, "sales": settings.sales_url}  # fmt: skip
    return lambda name: InternalClient(urls[name], settings.service_name, settings.service_token)


async def _limit(session: AsyncSession) -> Decimal:
    row = await session.get(AlertSettings, 1)
    return row.telegram_approval_max_usd if row and row.telegram_approval_max_usd is not None else DEFAULT_LIMIT


async def _branch(session: AsyncSession, branch_id: UUID) -> str:
    b = await session.get(KnownBranch, branch_id)
    return f"{b.code} {b.name_en}" if b else "Branch"


async def _name(session: AsyncSession, user_id: Any) -> str:
    s = await session.get(Staff, UUID(str(user_id))) if user_id else None
    return s.name if s else "staff"


def _why_app(a: Approval, limit: Decimal) -> str | None:
    if a.controlled:
        return "controlled"
    if a.needs_pin:
        return "pin"
    if a.value_usd is None:
        return "unknown"
    return "limit" if a.value_usd > limit else None


def _when(at: datetime | None) -> str:
    return (at or clock.now()).astimezone(clock.TIMEZONE).strftime("%d/%m %H:%M")


async def open_approval(session: AsyncSession, settings: Settings, *, kind: str, ref_id: Any, number: str,
                        branch_id: Any, value: Any, controlled: bool = False, needs_pin: bool = False,
                        needs_owner: bool = False, requested_by: Any = None,
                        details: dict[str, Any] | None = None) -> Approval | None:  # fmt: skip
    """One approval per (kind, ref): a replayed event adds nothing."""
    new_id = (await session.execute(insert(Approval).values(
        kind=kind, ref_id=UUID(str(ref_id)), number=number or "", branch_id=UUID(str(branch_id)),
        value_usd=Decimal(str(value)) if value is not None else None, controlled=bool(controlled),
        needs_pin=bool(needs_pin), needs_owner=bool(needs_owner), telegram_ok=False,
        requested_by=UUID(str(requested_by)) if requested_by else None, details=details or {}, status="pending",
        decided_name="", decided_via="", created_at=clock.now(),
    ).on_conflict_do_nothing(index_elements=["kind", "ref_id"]).returning(Approval.id))).scalar_one_or_none()  # fmt: skip
    if new_id is None:
        return None
    a = await session.get(Approval, new_id)
    why = _why_app(a, await _limit(session))
    a.telegram_ok = why is None
    k = KINDS[kind]
    link = f"{settings.web_url.rstrip('/')}{k.page}" if settings.web_url.startswith("https://") else None
    rows: list[list[dict[str, str]]] = []
    if a.telegram_ok:
        buttons = [{"text": "✅ អនុម័ត / Approve", "callback_data": f"ap:{a.id.hex}:a"}]
        if k.can_reject:
            buttons.append({"text": "❌ បដិសេធ / Reject", "callback_data": f"ap:{a.id.hex}:r"})
        rows.append(buttons)
    if link:
        rows.append([{"text": "📱 បើកក្នុងកម្មវិធី / Open in app", "url": link}])
    branch, who = await _branch(session, a.branch_id), await _name(session, requested_by)
    for target in (["owner"] if needs_owner else [str(a.branch_id), "owner"]):
        shown = None if a.value_usd is None or (k.cost and target != "owner") else f"{a.value_usd:.2f}"
        await queue(session, settings, key=f"approval:{a.id}:{target}", target=target, kind="approval",
                    text=texts.approval(kind, branch, a.number, who, a.details, shown, why, link),
                    branch_id=a.branch_id, subject_id=a.id, reply_markup={"inline_keyboard": rows} if rows else None)  # fmt: skip
    return a


async def _edit_messages(session: AsyncSession, settings: Settings, a: Approval) -> None:
    line = texts.approval_done(a.status, a.decided_name or "staff", _when(a.decided_at), a.decided_via)
    rows = (await session.execute(select(Message).where(Message.kind == "approval", Message.subject_id == a.id)
                                  .with_for_update())).scalars().all()  # fmt: skip
    for m in rows:
        if m.status == "queued":  # not out yet: it goes out already decided, without buttons
            m.text, m.reply_markup = f"{m.text}\n\n{line}", None
        elif m.status == "sent" and m.tg_message_id and m.chat_id:
            await queue(session, settings, key=f"approval_done:{a.id}:{m.id}", target=f"chat:{m.chat_id}",
                        kind="approval_done", text=f"{m.text}\n\n{line}", method="edit",
                        edit_message_id=m.tg_message_id, reply_markup={"inline_keyboard": []})  # fmt: skip


async def close(session: AsyncSession, settings: Settings, kind: str, ref_id: Any, status: str, by: Any = None,
                via: str = "app") -> Approval | None:  # fmt: skip
    """The owning service's event: decided (in the app or on Telegram), cancelled or expired."""
    a = (await session.execute(select(Approval).where(Approval.kind == kind, Approval.ref_id == UUID(str(ref_id)))
                               .with_for_update())).scalar_one_or_none()  # fmt: skip
    if a is None or a.status != "pending":
        return a
    a.status, a.decided_via, a.decided_at = status, via, clock.now()
    if by:
        a.decided_by, a.decided_name = UUID(str(by)), await _name(session, by)
    await _edit_messages(session, settings, a)
    return a


# ------------------------------------------------------------------ the tap


NOT_ALLOWED = "⛔ មិនអនុញ្ញាត / Not allowed"


def _refusal(a: Approval, access: dict[str, Any], limit: Decimal) -> str | None:
    """Why this person may not decide this on Telegram (None: they may)."""
    k = KINDS[a.kind]
    perms = set(access.get("permissions") or [])
    allowed = "*" in perms or (TELEGRAM_PERMISSION in perms and k.permission in perms)
    if not access.get("is_active") or not allowed:
        return f"{NOT_ALLOWED}: permission"
    if access.get("role") != "owner" and str(a.branch_id) not in {str(b) for b in access.get("branch_ids") or []}:
        return f"{NOT_ALLOWED}: branch"
    if _why_app(a, limit):
        return f"{NOT_ALLOWED}: open the app"
    if a.needs_owner and access.get("role") != "owner":
        return f"{NOT_ALLOWED}: owner only"
    return None


async def tap(session: AsyncSession, settings: Settings, sender: Sender, cb: dict[str, Any], clients: Clients) -> None:
    answer = cb.get("id") or ""
    try:
        _, raw, act = str(cb.get("data")).split(":")
        approval_id = UUID(hex=raw)
    except ValueError:
        return
    a = (await session.execute(select(Approval).where(Approval.id == approval_id).with_for_update())).scalar_one_or_none()
    if a is None:
        await sender.answer_callback(answer, "?")
        return
    if a.status != "pending":
        await sender.answer_callback(answer, texts.approval_done(a.status, a.decided_name or "staff",
                                                                 _when(a.decided_at), a.decided_via), alert=True)  # fmt: skip
        return
    link = await links.staff_link_of_user(session, str((cb.get("from") or {}).get("id") or ""))
    if link is None:
        await sender.answer_callback(answer, f"{NOT_ALLOWED}: link your Telegram in My profile", alert=True)
        return
    try:
        access = await clients("auth").get(f"/users/{link.subject_id}/access")
    except AppError:
        await sender.answer_callback(answer, NOT_ALLOWED, alert=True)
        return
    refusal = _refusal(a, access, await _limit(session))
    decision = "approve" if act == "a" else "reject"
    if refusal is None and decision == "reject" and not KINDS[a.kind].can_reject:
        refusal = f"{NOT_ALLOWED}: open the app"
    if refusal:
        await sender.answer_callback(answer, refusal, alert=True)
        return
    actor = Actor(**access)
    k = KINDS[a.kind]
    try:
        await clients(k.service).post(k.path.format(id=a.ref_id), {
            "decision": decision, "actor": actor.model_dump(mode="json"),
            "reason": f"Rejected on Telegram by {actor.name or 'staff'}"[:255]},
            actor=acting_user(actor), branch_id=a.branch_id)  # fmt: skip
    except AppError as exc:
        if exc.status_code == 409:  # decided in the app first (or expired): show it, buttons go
            a.status, a.decided_at, a.decided_via = "closed", clock.now(), ""
            await _edit_messages(session, settings, a)
        await sender.answer_callback(answer, exc.message[:190], alert=True)
        return
    a.status = "approved" if decision == "approve" else "rejected"
    a.decided_by, a.decided_name, a.decided_via, a.decided_at = actor.user_id, actor.name, "telegram", clock.now()
    await _edit_messages(session, settings, a)
    await sender.answer_callback(answer, "✅" if decision == "approve" else "❌")


# ------------------------------------------------------------------ events


async def handle(session: AsyncSession, settings: Settings, event_type: str, p: dict[str, Any]) -> bool:
    kind, _, what = event_type.partition(".")
    if event_type == "shrinkage.created" and p.get("status") == "pending_approval":
        await open_approval(session, settings, kind="shrinkage", ref_id=p["shrinkage_id"], number=p.get("number", ""),
                            branch_id=p["branch_id"], value=p.get("value"), controlled=p.get("is_controlled", False),
                            needs_pin=p.get("is_controlled", False), requested_by=p.get("created_by"),
                            details={"qty_base": p.get("qty_base"), "lot_no": p.get("lot_no"), "reason": p.get("reason")})  # fmt: skip
    elif kind == "shrinkage" and what in ("approved", "rejected"):
        await close(session, settings, "shrinkage", p["shrinkage_id"], what, p.get("decided_by"))
    elif event_type == "count.submitted":
        lines = p.get("lines") or []
        await open_approval(session, settings, kind="count", ref_id=p["count_id"], number=p.get("number", ""),
                            branch_id=p["branch_id"], value=p.get("variance_value"),
                            controlled=any(x.get("is_controlled") for x in lines), needs_pin=bool(p.get("needs_pin")),
                            needs_owner=bool(p.get("needs_owner")), requested_by=p.get("submitted_by"),
                            details={"lines": len(lines)})  # fmt: skip
    elif event_type in ("count.approved", "count.cancelled"):
        await close(session, settings, "count", p["count_id"], "approved" if what == "approved" else "closed",
                    p.get("approved_by"), p.get("via") or "app")  # fmt: skip
    elif event_type == "transfer_request.created" and p.get("status") == "requested":
        names = {b: await _branch(session, UUID(p[b])) for b in ("from_branch_id", "to_branch_id")}
        await open_approval(session, settings, kind="transfer_request", ref_id=p["request_id"], number=p.get("number", ""),
                            branch_id=p["from_branch_id"], value=p.get("value"), controlled=p.get("has_controlled", False),
                            requested_by=p.get("requested_by"),
                            details={"lines": len(p.get("lines") or []), "from": names["from_branch_id"],
                                     "to": names["to_branch_id"]})  # fmt: skip
    elif kind == "transfer_request" and what in ("approved", "rejected", "cancelled"):
        await close(session, settings, "transfer_request", p["request_id"], "closed" if what == "cancelled" else what,
                    p.get("decided_by"), p.get("via") or "app")  # fmt: skip
    elif event_type == "purchase_request.created" and p.get("status") == "submitted":
        await open_approval(session, settings, kind="purchase_request", ref_id=p["request_id"], number=p.get("number", ""),
                            branch_id=p["branch_id"], value=p.get("value"), controlled=p.get("has_controlled", False),
                            requested_by=p.get("requested_by"), details={"lines": len(p.get("lines") or [])})  # fmt: skip
    elif kind == "purchase_request" and what in ("approved", "rejected", "cancelled"):
        await close(session, settings, "purchase_request", p["request_id"], "closed" if what == "cancelled" else what,
                    p.get("decided_by"), p.get("via") or "app")  # fmt: skip
    elif event_type == "discount_approval.requested":
        await open_approval(session, settings, kind="discount", ref_id=p["approval_id"], number="",
                            branch_id=p["branch_id"], value=p.get("discount_usd"), needs_owner=bool(p.get("needs_owner")),
                            requested_by=p.get("seller_id"),
                            details={"pct": p.get("worst_pct"), "cap": p.get("cap_pct"), "discount": p.get("discount_usd"),
                                     "total": p.get("total_usd")})  # fmt: skip
    elif event_type == "discount_approval.decided":
        await close(session, settings, "discount", p["approval_id"], p.get("status") or "closed", p.get("approver_id"),
                    p.get("via") or "app")  # fmt: skip
    else:
        return kind in ("shrinkage", "count", "transfer_request", "purchase_request", "discount_approval")
    return True
