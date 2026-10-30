"""Purchase orders. Rules:

- Number per branch and year without gaps: PP1-PO-2026-000001.
- Lines: an active pack unit of an active medicine, qty in pack units (stored
  also in base units), unit_cost in USD per pack unit. One line per pack unit.
- draft → sent (a plain status change that locks the lines) → partially_received
  → received. Lines and supplier can be edited only in draft.
- Cancel (reason required) only while nothing was received. Never deleted.
- Staff see and act on POs of their own branches only (others: 404).
- Every change: purchase_order.* event with the whole PO (the document service
  prints the PDF from it) + a User Log entry.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.numbering import next_number
from pharmacy_shared.outbox import add_event

from ..models import DocSequence, KnownBranch, OutboxEvent, POGroup, POLine, PurchaseOrder
from .common import audit, branch_for, clean, commit, not_found, pack_unit_for, products_by_id
from .suppliers import active_supplier

COST = Decimal("0.0001")


def po_state(message: str, status: str) -> AppError:
    return AppError(ErrorCode.PO_STATE, message, status_code=409, details={"status": status})


async def event_payload(session: AsyncSession, po: PurchaseOrder) -> dict[str, Any]:
    """The whole PO with names, for the PDF and for reports."""
    branch = await session.get(KnownBranch, po.branch_id)
    products = await products_by_id(session, {line.medicine_id for line in po.lines})
    lines = []
    for line in po.lines:
        product = products.get(line.medicine_id)
        pack = next((p for p in product.pack_units if p.id == line.pack_unit_id), None) if product else None
        lines.append({
            "line_no": line.line_no, "po_line_id": str(line.id), "medicine_id": str(line.medicine_id),
            "sku": product.sku if product else "", "name": product.display_name if product else "",
            "name_km": product.name_km if product else "", "strength": product.strength if product else "",
            "dosage_form": product.dosage_form if product else "",
            "base_unit": product.base_unit if product else "",
            "pack_unit_id": str(line.pack_unit_id), "pack_unit": pack.name if pack else "",
            "qty_in_base": line.qty_in_base, "qty": line.qty, "qty_base": line.qty_base,
            "unit_cost": str(line.unit_cost), "line_total": str(line.line_total),
            "qty_received_base": line.qty_received_base,
        })  # fmt: skip
    s = po.supplier
    group = await session.get(POGroup, po.group_id) if po.group_id else None
    return {
        "purchase_order_id": str(po.id), "version": po.version, "number": po.number, "status": po.status,
        "branch": {"id": str(po.branch_id), "code": branch.code if branch else "",
                   "name_en": branch.name_en if branch else "", "name_km": branch.name_km if branch else ""},
        "supplier": {"id": str(s.id), "code": s.code, "name": s.name, "name_km": s.name_km,
                     "phone": s.phone, "address": s.address, "payment_terms_days": s.payment_terms_days},
        "note": po.note, "expected_on": po.expected_on.isoformat() if po.expected_on else None,
        "created_at": po.created_at.isoformat() if po.created_at else None,
        "sent_at": po.sent_at.isoformat() if po.sent_at else None,
        "cancel_reason": po.cancel_reason, "total": str(po.total), "lines": lines,
        "group": {"id": str(group.id), "number": group.number} if group else None,
    }  # fmt: skip


async def _publish(session: AsyncSession, po: PurchaseOrder, event: str) -> None:
    await session.flush()
    add_event(session, OutboxEvent, event, await event_payload(session, po))


publish = _publish


def _summary(po: PurchaseOrder) -> dict[str, Any]:
    return {
        "number": po.number, "status": po.status, "supplier": po.supplier.code, "note": po.note,
        "expected_on": po.expected_on.isoformat() if po.expected_on else None,
        "lines": [f"{line.qty} x {line.pack_unit_id} @ {line.unit_cost}" for line in po.lines],
        "total": str(po.total),
    }  # fmt: skip


# ---------------------------------------------------------------- reading


@dataclass(frozen=True)
class POFilter:
    branch_id: UUID | None = None
    supplier_id: UUID | None = None
    status: str | None = None
    q: str | None = None


def _branch_scope(query, actor: CurrentUser, model):  # noqa: ANN001, ANN202
    if not actor.is_owner:
        query = query.where(model.branch_id.in_(actor.branch_ids or [UUID(int=0)]))
    return query


async def list_orders(
    session: AsyncSession, actor: CurrentUser, f: POFilter, page: int, size: int
) -> tuple[list[PurchaseOrder], int]:
    query = _branch_scope(select(PurchaseOrder), actor, PurchaseOrder)
    if f.branch_id:
        query = query.where(PurchaseOrder.branch_id == f.branch_id)
    if f.supplier_id:
        query = query.where(PurchaseOrder.supplier_id == f.supplier_id)
    if f.status:
        query = query.where(PurchaseOrder.status == f.status)
    if f.q and clean(f.q):
        query = query.where(PurchaseOrder.number.ilike(f"%{clean(f.q).replace('%', '').replace('_', '')}%"))
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = await session.execute(
        query.order_by(PurchaseOrder.created_at.desc(), PurchaseOrder.id)
        .offset((page - 1) * size)
        .limit(size)
    )
    return list(rows.scalars()), int(total)


async def get_order(
    session: AsyncSession, actor: CurrentUser, po_id: UUID, *, lock: bool = False
) -> PurchaseOrder:
    query = select(PurchaseOrder).where(PurchaseOrder.id == po_id)
    po = (await session.execute(query.with_for_update() if lock else query)).scalar_one_or_none()
    if po is None or not actor.can_access_branch(po.branch_id):
        raise not_found("Purchase order")  # other branches look like missing
    return po


# ---------------------------------------------------------------- writing


async def _build_lines(session: AsyncSession, raw: list[dict[str, Any]]) -> list[POLine]:
    seen: set[UUID] = set()
    lines = []
    for i, item in enumerate(raw, start=1):
        pack = await pack_unit_for(session, item["medicine_id"], item["pack_unit_id"], line=i)
        if pack.id in seen:
            raise AppError(ErrorCode.VALIDATION_ERROR, f"Line {i}: {pack.product.sku} ({pack.name}) is listed twice",
                           status_code=422, details={"line": i})  # fmt: skip
        seen.add(pack.id)
        lines.append(POLine(
            line_no=i, medicine_id=pack.product_id, pack_unit_id=pack.id, qty=item["qty"],
            qty_base=item["qty"] * pack.qty_in_base, unit_cost=Decimal(str(item["unit_cost"])).quantize(COST),
            qty_received_base=0,
        ))  # fmt: skip
    return lines


async def create_order(session: AsyncSession, actor: CurrentUser, data: dict[str, Any]) -> PurchaseOrder:
    branch = await branch_for(session, actor, data["branch_id"])
    supplier = await active_supplier(session, data["supplier_id"])
    po = PurchaseOrder(
        branch_id=branch.id, supplier=supplier, status="draft", note=clean(data.get("note")),
        expected_on=data.get("expected_on"), version=1, created_by=actor.id,
        lines=await _build_lines(session, data["lines"]),
    )  # fmt: skip
    po.number = await next_number(session, DocSequence, branch.id, branch.code, "PO")
    session.add(po)
    await _publish(session, po, "purchase_order.created")
    audit(session, actor, "purchase_order.created", "purchase_order", po.id, branch_id=po.branch_id,
          after=_summary(po))  # fmt: skip
    await commit(session)
    return po


async def update_order(
    session: AsyncSession, actor: CurrentUser, po_id: UUID, data: dict[str, Any]
) -> PurchaseOrder:
    po = await get_order(session, actor, po_id, lock=True)
    if po.status != "draft":
        raise po_state("Only a draft purchase order can be edited", po.status)
    before = _summary(po)
    if data.get("supplier_id") is not None:
        po.supplier = await active_supplier(session, data["supplier_id"])
    if data.get("note") is not None:
        po.note = clean(data["note"])
    if "expected_on" in data:
        po.expected_on = data["expected_on"]
    if data.get("lines") is not None:
        new_lines = await _build_lines(session, data["lines"])
        po.lines.clear()
        await session.flush()  # free the line numbers before adding the new ones
        po.lines.extend(new_lines)
    after = _summary(po)
    if after != before:
        po.version += 1
        await _publish(session, po, "purchase_order.updated")
        old = {k: v for k, v in before.items() if after.get(k) != v}
        new = {k: v for k, v in after.items() if before.get(k) != v}
        audit(session, actor, "purchase_order.updated", "purchase_order", po.id, branch_id=po.branch_id,
              before=old, after=new)  # fmt: skip
    await commit(session)
    return po


async def send_order(session: AsyncSession, actor: CurrentUser, po_id: UUID) -> PurchaseOrder:
    """Marks the PO as sent to the supplier (no e-mail): its lines are now fixed
    and it can be received."""
    po = await get_order(session, actor, po_id, lock=True)
    if po.status != "draft":
        raise po_state("Only a draft purchase order can be sent", po.status)
    po.status = "sent"
    po.sent_at = clock.now()
    po.version += 1
    await _publish(session, po, "purchase_order.sent")
    audit(session, actor, "purchase_order.sent", "purchase_order", po.id, branch_id=po.branch_id,
          before={"status": "draft"}, after={"status": "sent"})  # fmt: skip
    await commit(session)
    return po


async def cancel_order(session: AsyncSession, actor: CurrentUser, po_id: UUID, reason: str) -> PurchaseOrder:
    po = await get_order(session, actor, po_id, lock=True)
    if po.status not in ("draft", "sent") or any(line.qty_received_base for line in po.lines):
        raise po_state("A purchase order can be cancelled only while nothing was received", po.status)
    before = po.status
    po.status = "cancelled"
    po.cancel_reason = clean(reason)
    po.version += 1
    from .requests import on_po_cancelled  # requests imports this module

    await on_po_cancelled(session, po.id)
    await _publish(session, po, "purchase_order.cancelled")
    audit(session, actor, "purchase_order.cancelled", "purchase_order", po.id, branch_id=po.branch_id,
          before={"status": before}, after={"status": "cancelled", "reason": po.cancel_reason})  # fmt: skip
    await commit(session)
    return po
