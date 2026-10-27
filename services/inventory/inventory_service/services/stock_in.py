"""Quick stock-in: goods that arrive without a purchase order. Rules:

- Same lot / expiry rules as receiving a PO: expiry before today (Asia/Phnom_Penh)
  → BATCH_EXPIRED; within 180 days → accepted, flagged short_expiry.
- A reason is required; the supplier is optional (from the local supplier copy).
- Each line: an active pack unit of an active medicine, qty in that pack unit,
  unit cost in USD per pack unit → a batch + an "in" movement, in one transaction.
- Idempotency-Key on the route; one User Log entry with all lines.
"""

from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode

from ..models import StockIn
from .common import audit, branch_for, clean, expiry_problem, find_pack_unit, is_short_expiry, supplier_for
from .movements import apply_movement, get_or_create_batch

COST = Decimal("0.0001")


async def stock_in(session: AsyncSession, actor: CurrentUser, data: dict[str, Any]) -> dict[str, Any]:
    branch = await branch_for(session, actor, data["branch_id"])
    supplier = await supplier_for(session, data.get("supplier_id"))
    record = StockIn(branch_id=branch.id, supplier_id=supplier.id if supplier else None,
                     reason=clean(data["reason"]), created_by=actor.id)  # fmt: skip
    session.add(record)
    await session.flush()
    lines = []
    for i, item in enumerate(data["lines"], start=1):
        pack = await find_pack_unit(session, item["medicine_id"], item["pack_unit_id"])
        if pack is None or not (pack.is_active and pack.product.is_active):
            raise AppError(ErrorCode.UNKNOWN_MEDICINE, f"Line {i}: unknown or inactive medicine / pack unit",
                           status_code=422, details={"line": i})  # fmt: skip
        if problem := expiry_problem(item["expiry_date"]):
            raise AppError(ErrorCode.BATCH_EXPIRED, f"Line {i}: lot {item['lot_no']} {problem}", status_code=409,
                           details={"line": i, "expiry_date": item["expiry_date"].isoformat()})  # fmt: skip
        unit_cost = Decimal(str(item["unit_cost"])).quantize(COST)
        batch = await get_or_create_batch(
            session, medicine_id=pack.product_id, lot_no=clean(item["lot_no"]), expiry_date=item["expiry_date"],
            supplier_id=record.supplier_id, cost_per_base=(unit_cost / pack.qty_in_base).quantize(COST),
        )  # fmt: skip
        qty_base = item["qty"] * pack.qty_in_base
        movement = await apply_movement(
            session, branch_id=branch.id, batch=batch, type="in", qty_base=qty_base, ref_type="stock_in_line",
            ref_id=f"{record.id}:{i}", reason=record.reason, actor_id=actor.id,
        )  # fmt: skip
        lines.append({
            "line_no": i, "medicine_id": pack.product_id, "sku": pack.product.sku, "pack_unit_id": pack.id,
            "pack_unit": pack.name, "qty": item["qty"], "qty_base": qty_base, "batch_id": batch.id,
            "lot_no": batch.lot_no, "expiry_date": batch.expiry_date, "short_expiry": is_short_expiry(batch.expiry_date),
            "unit_cost": unit_cost, "cost_per_base": batch.cost_per_base, "qty_after": movement.qty_after,
        })  # fmt: skip
    audit(session, actor, "stock_in.created", "stock_in", record.id, branch_id=branch.id, after={
        "reason": record.reason, "supplier": supplier.code if supplier else None,
        "lines": [f"{x['qty']} x {x['sku']} {x['pack_unit']} lot {x['lot_no']} exp {x['expiry_date']}" for x in lines],
        "short_expiry": [f"lot {x['lot_no']} exp {x['expiry_date']}" for x in lines if x["short_expiry"]],
    })  # fmt: skip
    await session.commit()
    return {"id": record.id, "branch_id": branch.id, "supplier_id": record.supplier_id, "reason": record.reason,
            "created_at": record.created_at, "lines": lines}  # fmt: skip
