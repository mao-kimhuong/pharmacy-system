"""Dispensing against prescriptions, for the sale saga (over /internal/v1) and
the invoice events. Rules:

check-and-hold (one call per sale, idempotent per invoice); rx/check (the cart
preview) runs the same code with hold=False: no row locks, nothing held or written:
- The Rx must be active or partly dispensed; past valid_until → RX_EXPIRED
  (hard stop, even before the daily job ran); draft / cancelled / fully
  dispensed → PRESCRIPTION_STATE.
- The sale line's medicine must be the Rx item's medicine.
- Quantity ≤ what remains (qty × (1 + repeats) − dispensed − held) and ≤ one
  fill (qty) → else RX_QUANTITY_EXCEEDED. Partial dispensing is fine.
- Allergy match → ALLERGY_WARNING (409) unless the line carries an override
  (pharmacist with prescriptions.override_warning and a typed reason – checked
  by sales, which records it). Duplicate therapy → DUPLICATE_THERAPY_WARNING
  (409) unless acknowledged. Messages in English and Khmer.
- Rows are locked (prescription, then items, in id order): two tills cannot
  dispense the same remaining quantity. The quantity is HELD until the sale
  ends; release (saga compensation) gives it back.

Invoice events (invoice.created / .cancelled / .returned):
- Each Rx line's hold follows the invoice: dispensed = sold − returned, 0 when
  cancelled. Targets are absolute and applied only for a newer invoice version,
  so duplicates and out-of-order events change nothing twice.
"""

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.internal import InternalCaller
from pharmacy_shared.outbox import add_event

from ..models import OPEN, OutboxEvent, Prescription, Product, RxHold, RxItem
from . import patients, prescriptions, safety, supply

log = logging.getLogger(__name__)


def _line_out(rx: Prescription, item: RxItem, line_no: int, warnings: list[dict]) -> dict[str, Any]:
    p = rx.patient
    return {
        "line_no": line_no, "rx_item_id": item.id, "prescription_id": rx.id, "prescription_number": rx.number,
        "patient_id": p.id, "patient_name_en": p.name_en, "patient_name_km": p.name_km,
        "doctor_name": rx.doctor.name, "dosage": item.dosage, "frequency": item.frequency,
        "duration_days": item.duration_days, "remaining_after": item.remaining_base, "warnings": warnings,
    }  # fmt: skip


async def _warnings(session: AsyncSession, rx: Prescription, item: RxItem) -> list[dict[str, Any]]:
    product = await session.get(Product, item.medicine_id)
    return safety.allergy_warnings(rx.patient, product) + await safety.duplicate_warnings(
        session, rx.patient_id, rx.id, product
    )


async def check_and_hold(
    session: AsyncSession, caller: InternalCaller, data: dict[str, Any]
) -> dict[str, Any]:
    hold = data.get("hold", True)
    invoice_id = data.get("invoice_id")
    existing = list((await session.execute(select(RxHold).where(RxHold.invoice_id == invoice_id))).scalars()) if hold else []
    if existing:  # the same sale asked again: same answer
        out = []
        for hold in existing:
            rx = await session.get(Prescription, hold.item.prescription_id)
            out.append(_line_out(rx, hold.item, hold.line_no, await _warnings(session, rx, hold.item)))
        return {"invoice_id": invoice_id, "lines": sorted(out, key=lambda x: x["line_no"])}

    lines = sorted(data["lines"], key=lambda x: str(x["rx_item_id"]))
    items = {i.id: i for i in (await session.execute(
        select(RxItem).where(RxItem.id.in_([x["rx_item_id"] for x in lines])))).scalars()}  # fmt: skip
    rx_ids = sorted({i.prescription_id for i in items.values()}, key=str)
    query = select(Prescription).where(Prescription.id.in_(rx_ids)).order_by(Prescription.id)
    if hold:
        query = query.with_for_update(of=Prescription).execution_options(populate_existing=True)
    rxs = {r.id: r for r in (await session.execute(query)).scalars()}
    if hold:
        await session.execute(
            select(RxItem.id).where(RxItem.id.in_(list(items))).order_by(RxItem.id).with_for_update()
        )
    for item in items.values():
        await session.refresh(item, attribute_names=["dispensed_base", "held_base"])

    today = clock.today()
    out, blocking = [], []
    held_now: dict[UUID, int] = {}
    for x in lines:
        item = items.get(x["rx_item_id"])
        details = {"line_no": x["line_no"], "rx_item_id": str(x["rx_item_id"])}
        if item is None:
            raise AppError(ErrorCode.NOT_FOUND, f"Line {x['line_no']}: prescription item not found", status_code=404,
                           details=details)  # fmt: skip
        rx = rxs[item.prescription_id]
        if rx.status == "expired" or (rx.status in OPEN and rx.valid_until < today):
            raise AppError(ErrorCode.RX_EXPIRED,
                           f"Prescription {rx.number} expired on {rx.valid_until} · វេជ្ជបញ្ជា {rx.number} "
                           f"ផុតសុពលភាពនៅថ្ងៃ {rx.valid_until}", status_code=422,
                           details={**details, "valid_until": rx.valid_until.isoformat()})  # fmt: skip
        if rx.status not in OPEN:
            raise AppError(ErrorCode.PRESCRIPTION_STATE, f"Prescription {rx.number} is {rx.status.replace('_', ' ')}",
                           status_code=409, details={**details, "status": rx.status})  # fmt: skip
        if item.medicine_id != x["medicine_id"]:
            raise AppError(ErrorCode.VALIDATION_ERROR, f"Line {x['line_no']}: the prescription is for another medicine",
                           status_code=422, details=details)  # fmt: skip
        remaining = item.remaining_base - held_now.get(item.id, 0)
        limit = min(remaining, item.qty_base)
        if x["qty_base"] > limit:
            raise AppError(
                ErrorCode.RX_QUANTITY_EXCEEDED,
                f"Line {x['line_no']}: {limit} can be dispensed now (left on the Rx {remaining}, one fill "
                f"{item.qty_base}) · បរិមាណលើសពីវេជ្ជបញ្ជា",
                status_code=422, details={**details, "remaining_base": remaining, "fill_base": item.qty_base},
            )  # fmt: skip
        held_now[item.id] = held_now.get(item.id, 0) + x["qty_base"]
        warnings = await _warnings(session, rx, item)
        allergies = [w for w in warnings if w["kind"] == "allergy"]
        duplicates = [w for w in warnings if w["kind"] == "duplicate_therapy"]
        if allergies and not x.get("allergy_override_reason"):
            blocking.append(("allergy", x["line_no"], allergies))
        if duplicates and not x.get("acknowledge_warnings"):
            blocking.append(("duplicate", x["line_no"], duplicates))
        out.append((rx, item, x, warnings))
    if blocking:
        code = (
            ErrorCode.ALLERGY_WARNING
            if any(k == "allergy" for k, _, _ in blocking)
            else ErrorCode.DUPLICATE_THERAPY_WARNING
        )
        first = blocking[0][2][0]
        raise AppError(code, f"{first['en']} · {first['km']}", status_code=409, details={
            "lines": [{"line_no": n, "warnings": w} for _, n, w in blocking]})  # fmt: skip

    if not hold:  # the preview: what the sale would get, nothing held
        lines = sorted((_line_out(rx, item, x["line_no"], w) for rx, item, x, w in out), key=lambda r: r["line_no"])
        await session.rollback()
        return {"invoice_id": None, "lines": lines}
    result = []
    for rx, item, x, warnings in out:
        item.held_base += x["qty_base"]
        hold = RxHold(rx_item_id=item.id, invoice_id=invoice_id, line_no=x["line_no"], branch_id=data["branch_id"],
                      qty_base=x["qty_base"], dispensed_base=0, status="held", version_seen=0, item=item)  # fmt: skip
        session.add(hold)
        await patients.link_branch(session, rx.patient_id, data["branch_id"])
        result.append(_line_out(rx, item, hold.line_no, warnings))
    await session.commit()
    return {"invoice_id": invoice_id, "lines": sorted(result, key=lambda r: r["line_no"])}


async def release(session: AsyncSession, caller: InternalCaller, invoice_id: UUID) -> dict[str, Any]:
    """Saga compensation: the sale did not complete; give the held quantity back."""
    holds = list((await session.execute(
        select(RxHold).where(RxHold.invoice_id == invoice_id, RxHold.status == "held").with_for_update(of=RxHold)
    )).scalars())  # fmt: skip
    for hold in holds:
        item = (
            await session.execute(select(RxItem).where(RxItem.id == hold.rx_item_id).with_for_update())
        ).scalar_one()
        item.held_base -= hold.qty_base
        hold.status = "released"
    await session.commit()
    return {"invoice_id": invoice_id, "released": len(holds)}


async def apply_invoice(session: AsyncSession, event_type: str, payload: dict[str, Any]) -> int:
    """invoice.created / .cancelled / .returned → dispensed quantities. Returns lines changed."""
    invoice_id = UUID(str(payload["invoice_id"]))
    version = int(payload.get("version") or 0)
    cancelled = payload.get("status") == "cancelled" or event_type == "invoice.cancelled"
    changed, touched, supplied = 0, set(), []
    for line in payload.get("lines") or []:
        if not line.get("rx_item_id"):
            continue
        hold = (await session.execute(select(RxHold).where(
            RxHold.invoice_id == invoice_id, RxHold.line_no == line["line_no"]).with_for_update(of=RxHold))).scalar_one_or_none()  # fmt: skip
        if hold is None or hold.status == "released" or version <= hold.version_seen:
            if hold is None or hold.status == "released":
                log.warning("invoice %s line %s: no open hold; ignored", invoice_id, line["line_no"])
            continue
        item = (
            await session.execute(select(RxItem).where(RxItem.id == hold.rx_item_id).with_for_update())
        ).scalar_one()
        if hold.status == "held":
            item.held_base -= hold.qty_base
            hold.status = "dispensed"
        target = 0 if cancelled else max(0, hold.qty_base - int(line.get("returned_qty_base") or 0))
        item.dispensed_base += target - hold.dispensed_base
        hold.dispensed_base = target
        hold.version_seen = version
        touched.add(item.prescription_id)
        supplied.append((item, target, line.get("name") or ""))
        changed += 1
    rxs = {}
    for rx_id in touched:
        rx = (await session.execute(select(Prescription).where(Prescription.id == rx_id).with_for_update(
            of=Prescription).execution_options(populate_existing=True))).scalar_one()  # fmt: skip
        prescriptions.refresh_status(rx)
        rx.version += 1
        rxs[rx_id] = rx
        await prescriptions.publish(session, rx, "prescription.dispensed")
    sold_on = clock.today()
    if payload.get("completed_at"):
        sold_on = datetime.fromisoformat(payload["completed_at"]).astimezone(clock.TIMEZONE).date()
    for item, qty, name in supplied:  # T2: refill reminders (notification) – qty 0 = nothing supplied any more
        ev = supply.supply_event(item, rxs[item.prescription_id], payload, qty, sold_on, name)
        if ev:
            add_event(session, OutboxEvent, "rx.supply", ev)
    return changed
