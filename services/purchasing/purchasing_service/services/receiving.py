"""Receiving goods against a sent purchase order. Rules:

- The PO must be sent or partially received (drafts can still change; goods
  without a PO go through the inventory Quick stock-in).
- Each line names a PO line, a lot number, an expiry date, qty in the PO line's
  pack unit and optionally a unit cost (default: the PO price). Several lines
  may name the same PO line (two lots of one item).
- Expiry before today (Asia/Phnom_Penh) → BATCH_EXPIRED; within
  `short_expiry_days` (180) → accepted, flagged short_expiry (response + User Log).
- More than ordered → RECEIVE_EXCEEDS_ORDER, unless allow_over=true and the user
  has purchasing.over_receive (owner, branch manager).
- Changing the unit cost needs the right to see costs.
- Creates a receipt (the supplier's bill, PP1-GRN-2026-000001, due after the
  supplier's payment terms) and emits goods.received; the inventory service
  turns each receipt line into a batch + "in" movement. Idempotency-Key on the route.
"""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.numbering import next_number
from pharmacy_shared.outbox import add_event

from ..config import get_settings
from ..models import DocSequence, KnownBranch, OutboxEvent, Receipt, ReceiptLine
from . import orders, requests
from .common import audit, can_see_cost, clean, commit, products_by_id

CENT = Decimal("0.01")
COST = Decimal("0.0001")


def goods_received_payload(r: Receipt) -> dict[str, Any]:
    return {
        "receipt_id": str(r.id), "number": r.number, "po_id": str(r.po_id), "po_number": r.po.number,
        "branch_id": str(r.branch_id), "supplier_id": str(r.supplier_id),
        "received_at": r.received_at.isoformat(), "received_by": str(r.received_by) if r.received_by else None,
        "total": str(r.total), "due_on": r.due_on.isoformat(), "supplier_invoice_no": r.supplier_invoice_no,
        "lines": [{
            "receipt_line_id": str(line.id), "medicine_id": str(line.medicine_id),
            "pack_unit_id": str(line.pack_unit_id), "qty_base": line.qty_base, "lot_no": line.lot_no,
            "expiry_date": line.expiry_date.isoformat(), "cost_per_base": str(line.cost_per_base),
            "line_total": str(line.line_total),
            "controlled_schedule": line.controlled_schedule, "is_controlled": bool(line.controlled_schedule),
        } for line in r.lines],
    }  # fmt: skip


async def receive(session: AsyncSession, actor: CurrentUser, po_id: UUID, data: dict[str, Any]) -> Receipt:
    po = await orders.get_order(session, actor, po_id, lock=True)
    if po.status not in ("sent", "partially_received"):
        raise orders.po_state("Goods can be received only on a sent purchase order", po.status)
    po_lines = {line.id: line for line in po.lines}
    today = clock.today()
    short_limit = today + timedelta(days=get_settings().short_expiry_days)
    products = await products_by_id(session, {line.medicine_id for line in po.lines})

    incoming: dict[UUID, int] = defaultdict(int)
    receipt_lines: list[ReceiptLine] = []
    for i, item in enumerate(data["lines"], start=1):
        po_line = po_lines.get(item["po_line_id"])
        if po_line is None:
            raise AppError(ErrorCode.VALIDATION_ERROR, f"Line {i}: not a line of this purchase order",
                           status_code=422, details={"line": i})  # fmt: skip
        expiry = item["expiry_date"]
        if expiry < today:
            raise AppError(ErrorCode.BATCH_EXPIRED, f"Line {i}: lot {item['lot_no']} expired on {expiry}",
                           status_code=409, details={"line": i, "expiry_date": expiry.isoformat()})  # fmt: skip
        if item.get("unit_cost") is not None and not can_see_cost(actor):
            raise AppError(ErrorCode.FORBIDDEN, "You cannot change purchase prices", status_code=403,
                           details={"permission": "purchasing.order"})  # fmt: skip
        unit_cost = (
            Decimal(str(item["unit_cost"])) if item.get("unit_cost") is not None else po_line.unit_cost
        )
        unit_cost = unit_cost.quantize(COST)
        qty_base = item["qty"] * po_line.qty_in_base
        incoming[po_line.id] += qty_base
        product = products.get(po_line.medicine_id)
        receipt_lines.append(ReceiptLine(
            line_no=i, po_line_id=po_line.id, medicine_id=po_line.medicine_id,
            pack_unit_id=po_line.pack_unit_id, lot_no=clean(item["lot_no"]), expiry_date=expiry,
            qty=item["qty"], qty_base=qty_base, unit_cost=unit_cost,
            cost_per_base=(unit_cost / po_line.qty_in_base).quantize(COST),
            line_total=(unit_cost * item["qty"]).quantize(CENT), short_expiry=expiry < short_limit,
            over_received=False, controlled_schedule=product.controlled_schedule if product else None,
        ))  # fmt: skip

    over = []
    over_ids: set[UUID] = set()
    for po_line_id, qty_base in incoming.items():
        line = po_lines[po_line_id]
        if line.qty_received_base + qty_base > line.qty_base:
            over_ids.add(po_line_id)
            over.append({"line_no": line.line_no, "ordered_base": line.qty_base,
                         "already_received_base": line.qty_received_base, "receiving_base": qty_base})  # fmt: skip
    if over:
        if not data.get("allow_over"):
            raise AppError(ErrorCode.RECEIVE_EXCEEDS_ORDER, "More than ordered. Check the quantities, or an owner "
                           "or manager can receive with allow_over", status_code=422, details={"lines": over})  # fmt: skip
        actor.require("purchasing.over_receive")
        for rl in receipt_lines:
            rl.over_received = rl.po_line_id in over_ids

    for po_line_id, qty_base in incoming.items():
        po_lines[po_line_id].qty_received_base += qty_base
    await requests.on_goods_received(session, dict(incoming))  # purchase requests this PO serves
    fully = all(line.qty_received_base >= line.qty_base for line in po.lines)
    old_status = po.status
    po.status = "received" if fully else "partially_received"
    po.version += 1

    branch = await session.get(KnownBranch, po.branch_id)
    receipt = Receipt(
        po=po, branch_id=po.branch_id, supplier=po.supplier,
        supplier_invoice_no=clean(data.get("supplier_invoice_no")), received_at=clock.now(),
        due_on=today + timedelta(days=po.supplier.payment_terms_days),
        total=sum((rl.line_total for rl in receipt_lines), Decimal("0.00")), paid=Decimal("0.00"),
        status="open", received_by=actor.id, lines=receipt_lines,
    )  # fmt: skip
    receipt.number = await next_number(
        session, DocSequence, po.branch_id, branch.code if branch else "BR", "GRN"
    )
    session.add(receipt)
    await session.flush()

    add_event(session, OutboxEvent, "goods.received", goods_received_payload(receipt))
    add_event(session, OutboxEvent, "purchase_order.received", await orders.event_payload(session, po))
    audit(session, actor, "goods.received", "receipt", receipt.id, branch_id=po.branch_id, after={
        "number": receipt.number, "po": po.number, "po_status": f"{old_status} → {po.status}",
        "supplier_invoice_no": receipt.supplier_invoice_no, "total": str(receipt.total),
        "lines": [f"{rl.qty} x {rl.pack_unit_id} lot {rl.lot_no} exp {rl.expiry_date}" for rl in receipt_lines],
        "short_expiry": [f"lot {rl.lot_no} exp {rl.expiry_date}" for rl in receipt_lines if rl.short_expiry],
        "over_received": [rl.line_no for rl in receipt_lines if rl.over_received],
    })  # fmt: skip
    await commit(session)
    return receipt


async def get_receipt(session: AsyncSession, actor: CurrentUser, receipt_id: UUID) -> Receipt:
    receipt = await session.get(Receipt, receipt_id)
    if receipt is None or not actor.can_access_branch(receipt.branch_id):
        raise AppError(ErrorCode.NOT_FOUND, "Receipt not found", status_code=404)
    return receipt
