"""Prescriptions. Rules:

- Numbered per branch: PP1-RX-2026-000001. Valid until issued_on + the branch's
  rx_valid_days (30 by default) unless given.
- draft: items and dates can change. activate: items are fixed. Then the status
  follows the balances: partly_dispensed / fully_dispensed. The daily job (or
  the date at dispense time) makes it expired. cancelled: reason, User Log;
  only while no sale is holding quantity. Never deleted.
- Items: an active medicine (local copy), qty in base units for ONE fill,
  dosage, frequency, duration, repeats. Allowed in total = qty × (1 + repeats).
- Staff see prescriptions of their branches (owner: all); others get 404.
- Every change: prescription.* event with the whole Rx (document prints the
  Rx summary from it) + User Log entry.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.numbering import next_number
from pharmacy_shared.outbox import add_event

from ..config import get_settings
from ..models import OPEN, BranchSettingsCopy, DocSequence, OutboxEvent, Prescription, Product, RxItem
from . import patients
from .common import audit, branch_for, clean, not_found, scope
from .doctors import get_doctor


def state_error(message: str, status: str) -> AppError:
    return AppError(ErrorCode.PRESCRIPTION_STATE, message, status_code=409, details={"status": status})


async def payload(session: AsyncSession, rx: Prescription) -> dict[str, Any]:
    products = {p.id: p for p in (await session.execute(
        select(Product).where(Product.id.in_([i.medicine_id for i in rx.items])))).scalars()}  # fmt: skip
    p, d = rx.patient, rx.doctor
    return {
        "prescription_id": str(rx.id), "version": rx.version, "number": rx.number, "rx_no": rx.rx_no, "status": rx.status,
        "branch_id": str(rx.branch_id), "issued_on": rx.issued_on.isoformat(), "valid_until": rx.valid_until.isoformat(),
        "patient": {"id": str(p.id), "name_km": p.name_km, "name_en": p.name_en, "sex": p.sex,
                    "dob": p.dob.isoformat() if p.dob else None, "phone": p.phone},
        "doctor": {"id": str(d.id), "name": d.name, "licence_no": d.licence_no, "clinic": d.clinic},
        "notes": rx.notes, "cancel_reason": rx.cancel_reason,
        "items": [{
            "rx_item_id": str(i.id), "line_no": i.line_no, "medicine_id": str(i.medicine_id),
            "sku": products[i.medicine_id].sku if i.medicine_id in products else "",
            "name": products[i.medicine_id].display_name if i.medicine_id in products else "",
            "name_km": products[i.medicine_id].name_km if i.medicine_id in products else "",
            "strength": products[i.medicine_id].strength if i.medicine_id in products else "",
            "base_unit": products[i.medicine_id].base_unit if i.medicine_id in products else "",
            "qty_base": i.qty_base, "dosage": i.dosage, "frequency": i.frequency, "duration_days": i.duration_days,
            "repeats_allowed": i.repeats_allowed, "repeats_used": i.repeats_used,
            "dispensed_base": i.dispensed_base, "remaining_base": i.remaining_base,
        } for i in rx.items],
    }  # fmt: skip


async def publish(session: AsyncSession, rx: Prescription, event: str) -> None:
    await session.flush()
    add_event(session, OutboxEvent, event, await payload(session, rx))


def refresh_status(rx: Prescription) -> bool:
    """Open and fully dispensed prescriptions follow their balances (a return or a
    cancelled sale reopens a fully dispensed one). Returns True when it changed."""
    if rx.status not in (*OPEN, "fully_dispensed"):
        return False
    if all(i.dispensed_base >= i.allowed_base for i in rx.items):
        new = "fully_dispensed"
    elif any(i.dispensed_base for i in rx.items):
        new = "partly_dispensed"
    else:
        new = "active"
    if new != rx.status:
        rx.status = new
        return True
    return False


# ---------------------------------------------------------------- reading


@dataclass(frozen=True)
class RxFilter:
    patient_id: UUID | None = None
    status: str | None = None
    q: str | None = None


async def get_rx(
    session: AsyncSession, actor: CurrentUser, rx_id: UUID, *, lock: bool = False
) -> Prescription:
    query = select(Prescription).where(Prescription.id == rx_id)
    rx = (
        await session.execute(query.with_for_update(of=Prescription) if lock else query)
    ).scalar_one_or_none()
    if rx is None or not actor.can_access_branch(rx.branch_id):
        raise not_found("Prescription")
    return rx


async def list_rx(session: AsyncSession, actor: CurrentUser, f: RxFilter, page: int, size: int):  # noqa: ANN201
    query = select(Prescription)
    if (branches := scope(actor)) is not None:
        query = query.where(Prescription.branch_id.in_(branches))
    if f.patient_id:
        query = query.where(Prescription.patient_id == f.patient_id)
    if f.status:
        query = query.where(Prescription.status == f.status)
    if f.q and clean(f.q):
        query = query.where(Prescription.number.ilike(f"%{clean(f.q).replace('%', '').replace('_', '')}%"))
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = await session.execute(query.order_by(Prescription.created_at.desc(), Prescription.id)
                                 .offset((page - 1) * size).limit(size))  # fmt: skip
    return list(rows.scalars()), int(total)


# ---------------------------------------------------------------- writing


async def _items(session: AsyncSession, raw: list[dict[str, Any]]) -> list[RxItem]:
    items = []
    for n, x in enumerate(raw, start=1):
        product = await session.get(Product, x["medicine_id"])
        if product is None or not product.is_active:
            raise AppError(ErrorCode.UNKNOWN_MEDICINE, f"Item {n}: unknown or inactive medicine", status_code=422,
                           details={"item": n})  # fmt: skip
        items.append(RxItem(
            line_no=n, medicine_id=product.id, qty_base=x["qty_base"], dosage=clean(x.get("dosage")),
            frequency=clean(x.get("frequency")), duration_days=x.get("duration_days"),
            repeats_allowed=x.get("repeats_allowed") or 0, dispensed_base=0, held_base=0,
        ))  # fmt: skip
    return items


async def _valid_until(session: AsyncSession, branch_id: UUID, data: dict[str, Any]):  # noqa: ANN202
    if data.get("valid_until"):
        return data["valid_until"]
    s = await session.get(BranchSettingsCopy, branch_id)
    days = s.rx_valid_days if s else get_settings().default_rx_valid_days
    return data["issued_on"] + timedelta(days=days)


def _dates(issued_on, valid_until) -> None:  # noqa: ANN001
    if valid_until < issued_on:
        raise AppError(ErrorCode.VALIDATION_ERROR, "valid_until is before the Rx date", status_code=422)


async def create_rx(session: AsyncSession, actor: CurrentUser, data: dict[str, Any]) -> Prescription:
    branch = await branch_for(session, actor, data["branch_id"])
    patient = await patients.get_patient(session, actor, data["patient_id"])
    if not patient.is_active:
        raise AppError(ErrorCode.VALIDATION_ERROR, "This patient is deactivated", status_code=422)
    doctor = await get_doctor(session, data["doctor_id"])
    if not doctor.is_active:
        raise AppError(ErrorCode.VALIDATION_ERROR, "This doctor is deactivated", status_code=422)
    valid_until = await _valid_until(session, branch.id, data)
    _dates(data["issued_on"], valid_until)
    rx = Prescription(branch_id=branch.id, patient=patient, doctor=doctor, rx_no=clean(data.get("rx_no")),
                      issued_on=data["issued_on"],
                      valid_until=valid_until, status="draft", notes=clean(data.get("notes")), version=1,
                      created_by=actor.id, items=await _items(session, data["items"]), attachments=[])  # fmt: skip
    rx.number = await next_number(session, DocSequence, branch.id, branch.code, "RX")
    session.add(rx)
    await patients.link_branch(session, patient.id, branch.id)
    await publish(session, rx, "prescription.created")
    audit(session, actor, "prescription.created", "prescription", rx.id, branch_id=branch.id, after={
        "number": rx.number, "patient": str(patient.id), "doctor": doctor.licence_no,
        "valid_until": valid_until.isoformat(), "items": len(rx.items)})  # fmt: skip
    await session.commit()
    return rx


async def update_rx(
    session: AsyncSession, actor: CurrentUser, rx_id: UUID, data: dict[str, Any]
) -> Prescription:
    rx = await get_rx(session, actor, rx_id, lock=True)
    if rx.status != "draft":
        raise state_error("Only a draft prescription can be changed", rx.status)
    before = {"issued_on": rx.issued_on.isoformat(), "valid_until": rx.valid_until.isoformat(), "notes": rx.notes,
              "doctor": str(rx.doctor.id), "items": len(rx.items)}  # fmt: skip
    if data.get("doctor_id"):
        rx.doctor = await get_doctor(session, data["doctor_id"])
    if data.get("issued_on"):
        rx.issued_on = data["issued_on"]
    if data.get("valid_until"):
        rx.valid_until = data["valid_until"]
    _dates(rx.issued_on, rx.valid_until)
    if data.get("rx_no") is not None:
        rx.rx_no = clean(data["rx_no"])
    if data.get("notes") is not None:
        rx.notes = clean(data["notes"])
    if data.get("items") is not None:
        new_items = await _items(session, data["items"])
        rx.items.clear()
        await session.flush()
        rx.items.extend(new_items)
    rx.version += 1
    await publish(session, rx, "prescription.updated")
    audit(session, actor, "prescription.updated", "prescription", rx.id, branch_id=rx.branch_id, before=before,
          after={"issued_on": rx.issued_on.isoformat(), "valid_until": rx.valid_until.isoformat(), "notes": rx.notes,
                 "doctor": str(rx.doctor.id), "items": len(rx.items)})  # fmt: skip
    await session.commit()
    return rx


async def activate(session: AsyncSession, actor: CurrentUser, rx_id: UUID) -> Prescription:
    rx = await get_rx(session, actor, rx_id, lock=True)
    if rx.status != "draft":
        raise state_error("Only a draft prescription can be activated", rx.status)
    if rx.valid_until < clock.today():
        raise AppError(
            ErrorCode.RX_EXPIRED, "This prescription is already past its valid-until date", status_code=422
        )
    rx.status, rx.activated_at = "active", clock.now()
    rx.version += 1
    await publish(session, rx, "prescription.activated")
    audit(session, actor, "prescription.activated", "prescription", rx.id, branch_id=rx.branch_id,
          before={"status": "draft"}, after={"status": "active"})  # fmt: skip
    await session.commit()
    return rx


async def cancel(session: AsyncSession, actor: CurrentUser, rx_id: UUID, reason: str) -> Prescription:
    rx = await get_rx(session, actor, rx_id, lock=True)
    if rx.status in ("cancelled", "fully_dispensed", "expired"):
        raise state_error(f"A {rx.status.replace('_', ' ')} prescription cannot be cancelled", rx.status)
    if any(i.held_base for i in rx.items):
        raise state_error("A sale is using this prescription right now; try again in a moment", rx.status)
    before = rx.status
    rx.status, rx.cancel_reason, rx.cancelled_at = "cancelled", clean(reason), clock.now()
    rx.version += 1
    await publish(session, rx, "prescription.cancelled")
    audit(session, actor, "prescription.cancelled", "prescription", rx.id, branch_id=rx.branch_id,
          before={"status": before}, after={"status": "cancelled", "reason": rx.cancel_reason})  # fmt: skip
    await session.commit()
    return rx


async def remaining(session: AsyncSession, actor: CurrentUser, rx_id: UUID) -> dict[str, Any]:
    """What can still be dispensed per item (the POS asks before adding Rx lines).
    Not dispensable when the Rx is not open or past valid_until."""
    rx = await get_rx(session, actor, rx_id)
    dispensable = rx.status in OPEN and rx.valid_until >= clock.today()
    products = {p.id: p for p in (await session.execute(
        select(Product).where(Product.id.in_([i.medicine_id for i in rx.items])))).scalars()}  # fmt: skip
    return {
        "prescription_id": rx.id, "number": rx.number, "status": rx.status, "valid_until": rx.valid_until,
        "dispensable": dispensable, "patient": rx.patient,
        "items": [{
            "rx_item_id": i.id, "line_no": i.line_no, "medicine_id": i.medicine_id,
            "name": products[i.medicine_id].display_name if i.medicine_id in products else "",
            "base_unit": products[i.medicine_id].base_unit if i.medicine_id in products else "",
            "fill_base": i.qty_base, "remaining_base": i.remaining_base,
            "can_dispense_now": min(i.remaining_base, i.qty_base) if dispensable else 0,
            "repeats_allowed": i.repeats_allowed, "repeats_used": i.repeats_used,
            "dosage": i.dosage, "frequency": i.frequency, "duration_days": i.duration_days,
        } for i in rx.items],
    }  # fmt: skip
