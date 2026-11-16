"""T2: a manual discount above the seller's cap, approved on Telegram instead of with the approver's PIN at the till.

- POST /carts/discount-approvals (pos.sell): the cart is checked like the preview; only when a discount is above
  the seller's cap. Pending for 10 minutes; discount_approval.requested → the notification service sends the
  approve / reject buttons (within the owner's Telegram limit).
- decide (notification, /internal/v1, as the user who tapped): the same rules as the PIN – someone else than the
  seller, a branch manager or the owner with sales.discount and that branch, the owner only when the seller is a
  manager or the discount is above the managers' cap. Once (pending only).
- The till polls GET /carts/discount-approvals/{id}; approved → it sends discount_approval_token "tg:<id>". The
  sale takes it once, by the same seller, for exactly that cart (pack, quantity and manual discount per line),
  within 10 minutes of the approval (DISCOUNT_APPROVAL_REQUIRED otherwise: ask again).
"""

import hashlib
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.outbox import add_event

from ..models import BranchSettingsCopy, DiscountApproval, OutboxEvent
from . import cart
from .clients import Clients
from .common import audit

PREFIX = "tg:"
VALID = timedelta(minutes=10)
APPROVERS = ("branch_manager", "owner")


def cart_hash(branch_id: UUID, lines: list[Any]) -> str:
    """What the approver agreed to: pack, quantity and manual discount of every line."""
    parts = [str(branch_id)] + [f"{x.pack.id}|{x.qty}|{Decimal(x.manual_discount):.2f}" for x in lines]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def _state(a: DiscountApproval, message: str) -> AppError:
    return AppError(ErrorCode.CART_STATE, message, status_code=409, details={"status": a.status})


def payload(a: DiscountApproval) -> dict[str, Any]:
    return {"approval_id": str(a.id), "branch_id": str(a.branch_id), "seller_id": str(a.seller_id),
            "seller_role": a.seller_role, "worst_pct": str(a.worst_pct), "cap_pct": str(a.cap_pct),
            "discount_usd": str(a.discount_usd), "total_usd": str(a.total_usd), "needs_owner": a.needs_owner,
            "status": a.status, "approver_id": str(a.approver_id) if a.approver_id else None,
            "expires_at": a.expires_at.isoformat()}  # fmt: skip


async def request(session: AsyncSession, actor: CurrentUser, clients: Clients, data: dict[str, Any]) -> DiscountApproval:
    from .checks import run_checks  # checks imports cart, which imports nothing from here

    result = await run_checks(session, actor, clients, {**data, "discount_approval_token": None}, "collect")
    settings = await session.get(BranchSettingsCopy, result.branch.id)
    caps = settings.max_discount_pct if settings and settings.max_discount_pct else cart.DEFAULT_CAPS
    worst = cart.over_cap(caps, actor.role, result.lines)
    if worst is None:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Every discount is within your cap: no approval needed",
                       status_code=422, details={"reason": "within_cap"})  # fmt: skip
    manager_cap = Decimal(str(caps.get("branch_manager", 0)))
    now = clock.now()
    a = DiscountApproval(branch_id=result.branch.id, seller_id=actor.id, seller_role=actor.role,
                         cart_hash=cart_hash(result.branch.id, result.lines), worst_pct=worst,
                         cap_pct=Decimal(str(caps.get(actor.role, 0))).quantize(Decimal("0.01")),
                         discount_usd=sum((x.manual_discount for x in result.lines), Decimal("0.00")),
                         total_usd=result.total, needs_owner=actor.role == "branch_manager" or worst > manager_cap,
                         status="pending", expires_at=now + VALID, created_at=now)  # fmt: skip
    session.add(a)
    await session.flush()
    add_event(session, OutboxEvent, "discount_approval.requested", payload(a))
    audit(session, actor, "discount_approval.requested", "discount_approval", a.id, branch_id=a.branch_id,
          after={"discount": str(a.discount_usd), "pct": str(worst), "cap": str(a.cap_pct)})  # fmt: skip
    await session.commit()
    return a


async def get(session: AsyncSession, actor: CurrentUser, approval_id: UUID, *, lock: bool = False) -> DiscountApproval:
    q = select(DiscountApproval).where(DiscountApproval.id == approval_id)
    a = (await session.execute(q.with_for_update() if lock else q)).scalar_one_or_none()
    if a is None or not actor.can_access_branch(a.branch_id) or (actor.id != a.seller_id and not actor.has("sales.discount")):
        raise AppError(ErrorCode.NOT_FOUND, "Discount approval not found", status_code=404)
    return a


async def decide(session: AsyncSession, approver: CurrentUser, approval_id: UUID, decision: str,
                 via: str) -> DiscountApproval:  # fmt: skip
    a = (await session.execute(select(DiscountApproval).where(DiscountApproval.id == approval_id)
                               .with_for_update())).scalar_one_or_none()  # fmt: skip
    if a is None:
        raise AppError(ErrorCode.NOT_FOUND, "Discount approval not found", status_code=404)
    if a.status != "pending":
        raise _state(a, f"This discount was already {a.status}")
    if a.expires_at <= clock.now():
        raise _state(a, "The till waited too long: the seller asks again")
    if approver.id == a.seller_id:
        raise AppError(ErrorCode.FORBIDDEN, "Someone else approves your discount", status_code=403)
    if approver.role not in APPROVERS or not approver.has("sales.discount") or not approver.can_access_branch(a.branch_id):
        raise AppError(ErrorCode.FORBIDDEN, "A branch manager or the owner approves discounts", status_code=403)
    if a.needs_owner and not approver.is_owner:
        raise AppError(ErrorCode.FORBIDDEN, "Only the owner approves this discount", status_code=403)
    a.status = "approved" if decision == "approve" else "rejected"
    a.approver_id, a.decided_at = approver.id, clock.now()
    add_event(session, OutboxEvent, "discount_approval.decided", {**payload(a), "via": via})
    audit(session, approver, f"discount_approval.{a.status}", "discount_approval", a.id, branch_id=a.branch_id,
          after={"discount": str(a.discount_usd), "pct": str(a.worst_pct), "seller": str(a.seller_id), "via": via})  # fmt: skip
    await session.commit()
    return a


async def use(session: AsyncSession, actor: CurrentUser, token: str, branch_id: UUID, lines: list[Any]) -> UUID:
    """The sale takes the approval (raise mode of the checks). Returns the approver."""
    try:
        approval_id = UUID(token[len(PREFIX):])
    except ValueError:
        approval_id = None
    a = (await session.execute(select(DiscountApproval).where(DiscountApproval.id == approval_id)
                               .with_for_update())).scalar_one_or_none() if approval_id else None  # fmt: skip
    ok = (a is not None and a.status == "approved" and a.seller_id == actor.id and a.branch_id == branch_id
          and a.decided_at is not None and a.decided_at + VALID > clock.now()
          and a.cart_hash == cart_hash(branch_id, lines))  # fmt: skip
    if not ok:
        raise AppError(ErrorCode.DISCOUNT_APPROVAL_REQUIRED,
                       "The Telegram approval does not fit this cart (changed, used, expired or not approved): ask again",
                       status_code=403, details={"reason": "telegram_approval_invalid"})  # fmt: skip
    a.status, a.used_at = "used", clock.now()
    return a.approver_id
