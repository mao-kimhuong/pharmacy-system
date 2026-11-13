"""Events the notification service listens to (queue `notification.events`):
copies of branches and staff (names in the texts), and the alerts.

Sent at once (to the branch's chat and the owner's): controlled register
discrepancy, register chain broken, account or PIN lockout, a below-cost sale,
a large manual discount (alert settings), a KHQR payment to refund by hand, a
recalled batch (S8b). Low stock and near expiry are kept
for the 07:30 digest (jobs.py). One message per event and chat (dedupe key).
"""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import copies
from pharmacy_shared.copies import BRANCH_EVENTS

from ..config import get_settings
from ..models import AlertSettings, FeatureCopy, KnownBranch, Staff, StockAlert
from . import approvals, customers, ops, texts
from .telegram import queue

ROUTING_KEYS = ("branch.*", "user.*", "stock.low", "batch.expiring", "register.discrepancy", "register.chain_broken",
                "invoice.created", "khqr.needs_refund", "khqr.review", "khqr.refunded", "khqr.reconciled",
                "batch.recalled", "feature.changed", *customers.ROUTING_KEYS, *approvals.ROUTING_KEYS)  # fmt: skip
OWNER = "owner"


async def _branch(session: AsyncSession, branch_id: Any) -> str:
    b = await session.get(KnownBranch, UUID(str(branch_id))) if branch_id else None
    return f"{b.code} {b.name_en}" if b else "Branch"


async def _staff(session: AsyncSession, user_id: Any) -> Staff | None:
    return await session.get(Staff, UUID(str(user_id))) if user_id else None


async def _both(session: AsyncSession, key: str, kind: str, branch_id: Any, text_branch: str, text_owner: str) -> None:
    settings = get_settings()
    if branch_id:
        await queue(session, settings, key=f"{key}:branch", target=str(branch_id), kind=kind, text=text_branch,
                    branch_id=UUID(str(branch_id)))  # fmt: skip
    await queue(session, settings, key=f"{key}:owner", target=OWNER, kind=kind, text=text_owner,
                branch_id=UUID(str(branch_id)) if branch_id else None)  # fmt: skip


async def handle_event(session: AsyncSession, event_type: str, p: dict[str, Any], message_id: UUID) -> None:
    kind = event_type.split(".")[0]
    if event_type in BRANCH_EVENTS:
        await copies.upsert_branch(session, KnownBranch, p)
    elif kind == "user" and p.get("name") is not None:
        values = {"id": UUID(p["user_id"]), "name": p["name"], "branch_ids": [str(b) for b in p.get("branch_ids") or []]}
        await session.execute(insert(Staff).values(**values).on_conflict_do_update(
            index_elements=["id"], set_={"name": values["name"], "branch_ids": values["branch_ids"]}))  # fmt: skip
    elif event_type in ("user.locked", "user.pin_locked"):
        who = await _staff(session, p.get("user_id"))
        text = texts.locked(who.name if who else "A user", "PIN" if event_type == "user.pin_locked" else "account")
        branch = p.get("branch_id") or ((who.branch_ids or [None])[0] if who else None)
        await _both(session, f"{event_type}:{message_id}", "lockout", branch, text, text)
    elif event_type in ("user.2fa_disabled", "user.2fa_reset"):
        who = await _staff(session, p.get("user_id"))
        text = texts.two_factor(who.name if who else "A user", event_type == "user.2fa_disabled", str(p.get("by")))
        await queue(session, get_settings(), key=f"{event_type}:{message_id}", target=OWNER, kind="security", text=text)
    elif event_type in ("stock.low", "batch.expiring"):
        ref = p.get("batch_id") if event_type == "batch.expiring" else p.get("medicine_id")
        await session.execute(insert(StockAlert).values(
            kind=event_type.split(".")[1], ref=str(ref), day=date.fromisoformat(p["day"]),
            branch_id=UUID(p["branch_id"]), data={k: p.get(k) for k in (
                "sku", "name", "available", "reorder_point", "lot_no", "expiry_date", "days_left", "qty_base")},
        ).on_conflict_do_nothing())  # fmt: skip
    elif event_type == "register.discrepancy":
        text = texts.discrepancy(await _branch(session, p["branch_id"]), p, "a controlled medicine")
        await _both(session, f"discrepancy:{p['discrepancy_id']}", "controlled", p["branch_id"], text, text)
    elif event_type == "register.chain_broken":
        text = texts.chain_broken(await _branch(session, p["branch_id"]), str(p.get("medicine_id"))[:8])
        await _both(session, f"chain:{message_id}", "controlled", p["branch_id"], text, text)
    elif event_type == "khqr.needs_refund":
        text = texts.khqr_refund(await _branch(session, p["branch_id"]), p)
        await _both(session, f"khqr:{p.get('refund_id') or p['khqr_id']}", "khqr_refund", p["branch_id"], text, text)
    elif event_type == "khqr.review":
        text = texts.khqr_review(await _branch(session, p["branch_id"]), p)
        await _both(session, f"khqr_review:{p['khqr_id']}", "khqr_refund", p["branch_id"], text, text)
    elif event_type == "khqr.refunded":
        text = texts.khqr_refunded(await _branch(session, p["branch_id"]), p)
        await _both(session, f"khqr_refunded:{p['refund_id']}", "khqr_refund", p["branch_id"], text, text)
    elif event_type == "khqr.reconciled":
        text = texts.khqr_reconciled(await _branch(session, p["branch_id"]), p)
        await _both(session, f"khqr_check:{p['branch_id']}:{p['date']}", "khqr_refund", p["branch_id"], text, text)
    elif event_type == "batch.recalled":
        text = texts.recall(await _branch(session, p["branch_id"]), p)
        await _both(session, f"recall:{p['recall_id']}:{p['branch_id']}", "recall", p["branch_id"], text, text)
    elif event_type == "invoice.created":
        await money_alerts(session, p)
        await customers.handle(session, get_settings(), event_type, p)
        await ops.on_invoice(session, p)
    elif event_type == "feature.changed":
        await session.execute(insert(FeatureCopy).values(key=p["key"], enabled=bool(p["enabled"])).on_conflict_do_update(
            index_elements=["key"], set_={"enabled": bool(p["enabled"])}))  # fmt: skip
    elif not await approvals.handle(session, get_settings(), event_type, p):
        await customers.handle(session, get_settings(), event_type, p)


async def money_alerts(session: AsyncSession, inv: dict[str, Any]) -> None:
    s = await session.get(AlertSettings, 1) or AlertSettings(large_discount_pct=Decimal("20"),
                                                             large_discount_usd=Decimal("10"))  # fmt: skip
    lines = inv.get("lines") or []

    def D(v: Any) -> Decimal:  # noqa: N802
        return Decimal(str(v or "0"))

    below = [x for x in lines if D(x.get("net")) < D(x.get("cost"))]
    manual_total = sum((D(x.get("manual_discount")) for x in lines), Decimal("0"))
    big = [x for x in lines if D(x.get("manual_discount")) > 0 and D(x.get("line_total")) > 0
           and D(x.get("manual_discount")) * 100 / D(x.get("line_total")) >= s.large_discount_pct]  # fmt: skip
    if manual_total >= s.large_discount_usd > 0:
        big = [x for x in lines if D(x.get("manual_discount")) > 0]
    branch_id = inv["branch"]["id"]
    branch = await _branch(session, branch_id)
    staff = await _staff(session, inv.get("cashier_id"))
    name = staff.name if staff else "staff"
    for kind, chosen in (("below_cost", below), ("large_discount", big)):
        if chosen:
            await _both(session, f"{kind}:{inv['invoice_id']}", kind, branch_id,
                        texts.money_alert(branch, inv.get("number") or "", name, kind, chosen, show_cost=False),
                        texts.money_alert(branch, inv.get("number") or "", name, kind, chosen, show_cost=True))  # fmt: skip
