"""Purchase requests. Rules:

- A branch asks (purchasing.request, own branch): medicine, quantity, reason,
  needed-by date. Number PP1-PR-2026-000001.
- A manager or the owner approves or rejects it (purchasing.request_approve,
  that branch; reason for rejecting). The requester may cancel it while it waits.
- Approved lines are either
  (a) ordered (purchasing.order): lines of one or more branches + one supplier
      → one PO per branch (S2 POs, unchanged) sharing a group number
      (PP1-PG-…); the same pack unit of one branch becomes one PO line; or
  (b) filled by a transfer (purchasing.request_approve): inventory makes an
      approved transfer request + transfer from the source branch.
- Progress follows: PO receipts and transfer events fill `fulfilled_base`;
  a cancelled PO or transfer puts the lines back to approved.
- Re-order lists create requests through /internal/v1 (once per source_ref).
- Every change: purchase_request.* event + User Log entry. Never deleted.
"""

import hashlib
from collections import defaultdict
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.internal import InternalClient
from pharmacy_shared.numbering import next_number
from pharmacy_shared.outbox import add_event

from ..models import (
    DocSequence,
    KnownBranch,
    OutboxEvent,
    POGroup,
    POLine,
    PurchaseOrder,
    PurchaseRequest,
    PurchaseRequestLine,
)
from . import orders
from .common import audit, branch_for, clean, not_found, pack_unit_for, products_by_id
from .suppliers import active_supplier

COST = Decimal("0.0001")


def _state(message: str, status: str) -> AppError:
    return AppError(ErrorCode.REQUEST_STATE, message, status_code=409, details={"status": status})


def progress(r: PurchaseRequest) -> str:
    """What the requesting branch sees."""
    if r.status != "approved":
        return r.status
    live = [x for x in r.lines if x.status not in ("rejected", "cancelled")]
    if live and all(x.status == "fulfilled" for x in live):
        return "fulfilled"
    if any(x.fulfilled_base for x in live):
        return "partly_fulfilled"
    if any(x.status == "ordered" for x in live):
        return "ordered"
    if any(x.status == "transferring" for x in live):
        return "transferring"
    return "approved"


def payload(r: PurchaseRequest) -> dict[str, Any]:
    return {
        "request_id": str(r.id), "number": r.number, "branch_id": str(r.branch_id), "status": r.status,
        "progress": progress(r), "version": r.version, "source_ref": r.source_ref,
        "lines": [{"line_id": str(x.id), "medicine_id": str(x.medicine_id), "qty_base": x.qty_base,
                   "status": x.status, "po_number": x.po_number, "transfer_number": x.transfer_number,
                   "fulfilled_base": x.fulfilled_base} for x in r.lines],
    }  # fmt: skip


def _event(session: AsyncSession, r: PurchaseRequest, name: str) -> None:
    r.version += 1
    add_event(session, OutboxEvent, name, payload(r))


async def _updated(session: AsyncSession, requests: set[PurchaseRequest] | list[PurchaseRequest]) -> None:
    """Requests reached through their lines: load their lines, then publish."""
    await session.flush()
    for r in requests:
        await session.refresh(r, attribute_names=["lines"])
        _event(session, r, "purchase_request.updated")


async def get_request(session: AsyncSession, actor: CurrentUser, request_id: UUID, *, lock: bool = False
                      ) -> PurchaseRequest:  # fmt: skip
    query = select(PurchaseRequest).where(PurchaseRequest.id == request_id)
    r = (
        await session.execute(query.with_for_update(of=PurchaseRequest) if lock else query)
    ).scalar_one_or_none()
    if r is None or not actor.can_access_branch(r.branch_id):
        raise not_found("Purchase request")
    return r


async def list_requests(
    session: AsyncSession, actor: CurrentUser, branch_id: UUID | None, status: str | None
):  # noqa: ANN201
    query = select(PurchaseRequest)
    if branch_id:
        actor.require_branch(branch_id)
        query = query.where(PurchaseRequest.branch_id == branch_id)
    elif not actor.is_owner:
        query = query.where(PurchaseRequest.branch_id.in_(list(actor.branch_ids) or [UUID(int=0)]))
    if status:
        query = query.where(PurchaseRequest.status == status)
    return list(
        (await session.execute(query.order_by(PurchaseRequest.created_at.desc()).limit(500))).scalars()
    )


async def _build(session: AsyncSession, branch: KnownBranch, data: dict[str, Any], actor_id: UUID | None
                 ) -> PurchaseRequest:  # fmt: skip
    products = await products_by_id(session, {UUID(str(x["medicine_id"])) for x in data["lines"]})
    lines = []
    for i, x in enumerate(data["lines"], start=1):
        p = products.get(UUID(str(x["medicine_id"])))
        if p is None or not p.is_active:
            raise AppError(ErrorCode.UNKNOWN_MEDICINE, f"Line {i}: unknown or inactive medicine", status_code=422,
                           details={"line": i})  # fmt: skip
        lines.append(PurchaseRequestLine(line_no=i, medicine_id=p.id, qty_base=x["qty_base"],
                                         reason=clean(x.get("reason")), needed_by=x.get("needed_by"),
                                         status="submitted", source_ref=x.get("source_ref")))  # fmt: skip
    r = PurchaseRequest(branch_id=branch.id, status="submitted", note=clean(data.get("note")),
                        source_ref=data.get("source_ref"), requested_by=actor_id, version=0, lines=lines)  # fmt: skip
    r.number = await next_number(session, DocSequence, branch.id, branch.code, "PR")
    session.add(r)
    await session.flush()
    _event(session, r, "purchase_request.created")
    return r


async def create(session: AsyncSession, actor: CurrentUser, data: dict[str, Any]) -> PurchaseRequest:
    branch = await branch_for(session, actor, data["branch_id"])
    r = await _build(session, branch, data, actor.id)
    audit(session, actor, "purchase_request.created", "purchase_request", r.id, branch_id=branch.id,
          after={"number": r.number, "lines": [f"{x.qty_base} x {x.medicine_id}" for x in r.lines]})  # fmt: skip
    await session.commit()
    return r


async def create_internal(
    session: AsyncSession, data: dict[str, Any], actor_id: UUID | None
) -> PurchaseRequest:
    """From a re-order list: once per source_ref."""
    found = (await session.execute(select(PurchaseRequest).where(PurchaseRequest.source_ref == data["source_ref"]))
             ).scalar_one_or_none()  # fmt: skip
    if found:
        return found
    branch = await session.get(KnownBranch, data["branch_id"])
    if branch is None or not branch.is_active:
        raise AppError(ErrorCode.UNKNOWN_BRANCH, "Unknown or inactive branch", status_code=422)
    r = await _build(session, branch, data, actor_id)
    await session.commit()
    return r


async def decide(session: AsyncSession, actor: CurrentUser, request_id: UUID, action: str,
                 reason: str | None = None) -> PurchaseRequest:  # fmt: skip
    r = await get_request(session, actor, request_id, lock=True)
    if action == "cancel":
        actor.require("purchasing.request")
    else:
        actor.require("purchasing.request_approve")
    if r.status != "submitted":
        raise _state(f"This request is {r.status}", r.status)
    status = {"approve": "approved", "reject": "rejected", "cancel": "cancelled"}[action]
    if status != "approved" and not clean(reason):
        raise AppError(ErrorCode.VALIDATION_ERROR, "Give the reason", status_code=422)
    r.status, r.decided_by, r.decided_at, r.decision_reason = (
        status,
        actor.id,
        clock.now(),
        clean(reason) or None,
    )
    for line in r.lines:
        line.status = status
    _event(session, r, f"purchase_request.{status}")
    audit(session, actor, f"purchase_request.{status}", "purchase_request", r.id, branch_id=r.branch_id,
          after={"number": r.number, "reason": r.decision_reason})  # fmt: skip
    await session.commit()
    return r


async def _approved_lines(
    session: AsyncSession, actor: CurrentUser, line_ids: list[UUID]
) -> list[PurchaseRequestLine]:
    lines = list((await session.execute(select(PurchaseRequestLine).where(PurchaseRequestLine.id.in_(line_ids))
                                        .with_for_update(of=PurchaseRequestLine))).scalars())  # fmt: skip
    if len(lines) != len(set(line_ids)):
        raise not_found("Purchase request line")
    for line in lines:
        if not actor.can_access_branch(line.request.branch_id):
            raise not_found("Purchase request line")
        if line.status != "approved":
            raise _state(f"{line.request.number} line {line.line_no} is {line.status}", line.status)
    return lines


async def to_purchase_orders(session: AsyncSession, actor: CurrentUser, data: dict[str, Any]) -> POGroup:
    """Approved lines (any branches) + one supplier → one draft PO per branch, one group."""
    supplier = await active_supplier(session, data["supplier_id"])
    given = {x["request_line_id"]: x for x in data["lines"]}
    lines = await _approved_lines(session, actor, list(given))
    by_branch: dict[UUID, list[PurchaseRequestLine]] = defaultdict(list)
    for line in lines:
        by_branch[line.request.branch_id].append(line)
    first = await branch_for(session, actor, sorted(by_branch, key=str)[0])
    group = POGroup(supplier_id=supplier.id, created_by=actor.id)
    group.number = await next_number(session, DocSequence, first.id, first.code, "PG")
    session.add(group)
    await session.flush()
    for branch_id, branch_lines in sorted(by_branch.items(), key=lambda kv: str(kv[0])):
        branch = await branch_for(session, actor, branch_id)
        merged: dict[UUID, dict[str, Any]] = {}  # pack unit → PO line data + request lines it serves
        for line in sorted(branch_lines, key=lambda x: (x.request.number, x.line_no)):
            x = given[line.id]
            pack = await pack_unit_for(session, line.medicine_id, x["pack_unit_id"], line=line.line_no)
            entry = merged.setdefault(pack.id, {"pack": pack, "qty": 0, "unit_cost": Decimal(str(x["unit_cost"])),
                                                "lines": []})  # fmt: skip
            entry["qty"] += x["qty"]
            entry["lines"].append(line)
        po = PurchaseOrder(branch_id=branch.id, supplier=supplier, status="draft", note=clean(data.get("note")),
                           expected_on=data.get("expected_on"), version=1, created_by=actor.id, group_id=group.id,
                           lines=[POLine(line_no=i, medicine_id=e["pack"].product_id, pack_unit_id=e["pack"].id,
                                         qty=e["qty"], qty_base=e["qty"] * e["pack"].qty_in_base,
                                         unit_cost=e["unit_cost"].quantize(COST), qty_received_base=0)
                                  for i, e in enumerate(merged.values(), start=1)])  # fmt: skip
        po.number = await next_number(session, DocSequence, branch.id, branch.code, "PO")
        session.add(po)
        await session.flush()
        for po_line, e in zip(po.lines, merged.values(), strict=True):
            for line in e["lines"]:
                line.status, line.po_id, line.po_number, line.po_line_id = (
                    "ordered",
                    po.id,
                    po.number,
                    po_line.id,
                )
        await orders.publish(session, po, "purchase_order.created")
        audit(session, actor, "purchase_order.created", "purchase_order", po.id, branch_id=branch.id,
              after={"number": po.number, "group": group.number, "from_requests": sorted(
                  {x.request.number for e in merged.values() for x in e["lines"]})})  # fmt: skip
    await _updated(session, {line.request for line in lines})
    audit(session, actor, "po_group.created", "po_group", group.id, after={
        "number": group.number, "supplier": supplier.code, "branches": len(by_branch)})  # fmt: skip
    await session.commit()
    return group


async def fill_by_transfer(session: AsyncSession, actor: CurrentUser, inventory: InternalClient, request_id: UUID,
                           data: dict[str, Any]) -> PurchaseRequest:  # fmt: skip
    r = await get_request(session, actor, request_id, lock=True)
    actor.require("purchasing.request_approve")
    lines = [x for x in await _approved_lines(session, actor, data["line_ids"]) if x.request_id == r.id]
    if len(lines) != len(data["line_ids"]):
        raise not_found("Purchase request line")
    if data["source_branch_id"] == r.branch_id:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Choose another branch as the source", status_code=422)
    source_ref = "pr:" + hashlib.sha256(",".join(sorted(str(x.id) for x in lines)).encode()).hexdigest()[:40]
    made = await inventory.post("/transfers/from-purchase-request", {
        "source_ref": source_ref, "from_branch_id": str(data["source_branch_id"]), "to_branch_id": str(r.branch_id),
        "reason": f"Purchase request {r.number}",
        "lines": [{"medicine_id": str(x.medicine_id), "qty_base": x.qty_base, "source_ref": str(x.id)} for x in lines],
    }, actor=actor, branch_id=r.branch_id)  # fmt: skip
    for line in lines:
        line.status, line.transfer_id = "transferring", UUID(str(made["transfer_id"]))
        line.transfer_number = made["transfer_number"]
    _event(session, r, "purchase_request.updated")
    audit(session, actor, "purchase_request.transfer", "purchase_request", r.id, branch_id=r.branch_id, after={
        "number": r.number, "transfer": made["transfer_number"], "source": str(data["source_branch_id"])})  # fmt: skip
    await session.commit()
    return r


# ---------------------------------------------------------------- progress from POs and transfers


async def on_goods_received(session: AsyncSession, received: dict[UUID, int]) -> None:
    """po line id → base units just received: fills the request lines it serves, oldest first."""
    if not received:
        return
    lines = list((await session.execute(
        select(PurchaseRequestLine).join(PurchaseRequest, PurchaseRequest.id == PurchaseRequestLine.request_id)
        .where(PurchaseRequestLine.po_line_id.in_(list(received)))
        .order_by(PurchaseRequest.created_at, PurchaseRequest.number, PurchaseRequestLine.line_no))).unique().scalars())  # fmt: skip
    touched = set()
    for line in lines:
        left = received.get(line.po_line_id, 0)
        take = min(left, line.qty_base - line.fulfilled_base)
        if take <= 0:
            continue
        received[line.po_line_id] = left - take
        line.fulfilled_base += take
        if line.fulfilled_base >= line.qty_base:
            line.status = "fulfilled"
        touched.add(line.request)
    await _updated(session, touched)


async def on_po_cancelled(session: AsyncSession, po_id: UUID) -> None:
    lines = list(
        (
            await session.execute(select(PurchaseRequestLine).where(PurchaseRequestLine.po_id == po_id))
        ).scalars()
    )
    for line in lines:
        line.status, line.po_id, line.po_number, line.po_line_id = "approved", None, None, None
    await _updated(session, {line.request for line in lines})


async def on_transfer(session: AsyncSession, event_type: str, p: dict[str, Any]) -> None:
    """transfer.* → the request lines it fills (absolute figures, newer versions only)."""
    refs = {x["source_ref"]: x for x in p.get("lines") or [] if x.get("source_ref")}
    if not refs:
        return
    ids = []
    for ref in refs:
        try:
            ids.append(UUID(str(ref)))
        except ValueError:
            continue
    lines = list((await session.execute(select(PurchaseRequestLine).where(
        PurchaseRequestLine.id.in_(ids), or_(PurchaseRequestLine.transfer_id.is_(None),
                                             PurchaseRequestLine.transfer_id == UUID(p["transfer_id"])))
        .with_for_update(of=PurchaseRequestLine))).scalars())  # fmt: skip
    touched = set()
    for line in lines:
        if int(p["version"]) <= line.transfer_version:
            continue
        line.transfer_version = int(p["version"])
        tline = refs[str(line.id)]
        if p["status"] == "cancelled":
            line.status, line.transfer_id, line.transfer_number, line.fulfilled_base = (
                "approved",
                None,
                None,
                0,
            )
        else:
            line.transfer_id, line.transfer_number = UUID(p["transfer_id"]), p["number"]
            got = sum(min(x["qty_received"] or 0, x["qty_base"]) for x in p.get("picks") or []
                      if x["line_no"] == tline["line_no"])  # fmt: skip
            line.fulfilled_base = got
            # fulfilled when all arrived, or the transfer is closed (nothing more will come)
            line.status = "fulfilled" if got >= line.qty_base or p["status"] == "closed" else "transferring"
        touched.add(line.request)
    await _updated(session, touched)
