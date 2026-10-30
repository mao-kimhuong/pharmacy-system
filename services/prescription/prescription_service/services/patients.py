"""Patients and their allergies. Rules:

- Never deleted: deactivate (with a reason) / activate. Allergies are not
  deleted either: deactivated with a reason.
- A patient belongs to a home branch and is visible there and at every branch
  linked to them (a branch that wrote them an Rx, or found them by exact phone
  number). The owner sees all. Other branches get 404.
- Another branch finds an existing patient only by the exact phone number; that
  lookup is logged and links the branch.
- Opening a patient's record writes a User Log entry (privacy).
- Phones are normalized like staff phones. Optional link to a customer (local copy).
- Every change: patient.* event (the document service prints the Rx summary
  from it) + User Log entry.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.audit import changes
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.outbox import add_event
from pharmacy_shared.phone import normalize_phone

from ..models import KnownCustomer, OutboxEvent, Patient, PatientAllergy, PatientBranch
from .common import audit, branch_for, clean, not_found, scope


def payload(p: Patient) -> dict[str, Any]:
    return {
        "patient_id": str(p.id), "version": p.version, **p.safe_fields(),
        "home_branch_id": str(p.home_branch_id), "branch_ids": [str(b) for b in p.branch_ids],
        "allergies": [{"kind": a.kind, "value": a.value, "note": a.note} for a in p.active_allergies],
    }  # fmt: skip


def _event(session: AsyncSession, action: str, p: Patient) -> None:
    add_event(session, OutboxEvent, action, payload(p))


def _phone(raw: str | None) -> str:
    if not clean(raw):
        return ""
    try:
        return normalize_phone(raw)
    except ValueError as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Not a phone number", status_code=422,
                       details={"field": "phone"}) from exc  # fmt: skip


def _visible(actor: CurrentUser):  # noqa: ANN202
    branches = scope(actor)
    if branches is None:
        return None
    return exists().where(PatientBranch.patient_id == Patient.id, PatientBranch.branch_id.in_(branches))


async def link_branch(session: AsyncSession, patient_id: UUID, branch_id: UUID) -> bool:
    result = await session.execute(
        insert(PatientBranch).values(patient_id=patient_id, branch_id=branch_id).on_conflict_do_nothing()
    )
    return bool(result.rowcount)


async def get_patient(
    session: AsyncSession, actor: CurrentUser, patient_id: UUID, *, lock: bool = False
) -> Patient:
    query = select(Patient).where(Patient.id == patient_id)
    if (cond := _visible(actor)) is not None:
        query = query.where(cond)
    p = (await session.execute(query.with_for_update(of=Patient) if lock else query)).scalar_one_or_none()
    if p is None:
        raise not_found("Patient")
    return p


async def view_patient(session: AsyncSession, actor: CurrentUser, patient_id: UUID) -> Patient:
    """The full record (allergies, conditions, notes): logged every time."""
    p = await get_patient(session, actor, patient_id)
    audit(session, actor, "patient.viewed", "patient", p.id, branch_id=p.home_branch_id)
    await session.commit()
    return p


async def search(
    session: AsyncSession, actor: CurrentUser, q: str | None, include_inactive: bool, page: int, size: int
) -> tuple[list[Patient], int]:
    query = select(Patient)
    if (cond := _visible(actor)) is not None:
        query = query.where(cond)
    if q and clean(q):
        term = clean(q)
        like = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        conds = [Patient.name_en.ilike(like, escape="\\"), Patient.name_km.ilike(like, escape="\\")]
        try:
            conds.append(Patient.phone == normalize_phone(term))
        except ValueError:
            pass
        query = query.where(or_(*conds))
    if not include_inactive:
        query = query.where(Patient.is_active.is_(True))
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = await session.execute(query.order_by(func.lower(Patient.name_en), Patient.id)
                                 .offset((page - 1) * size).limit(size))  # fmt: skip
    return list(rows.scalars()), int(total)


async def _customer(session: AsyncSession, customer_id: UUID | None) -> UUID | None:
    if customer_id is None:
        return None
    c = await session.get(KnownCustomer, customer_id)
    if c is None or not c.is_active:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Unknown or inactive customer", status_code=422,
                       details={"field": "customer_id"})  # fmt: skip
    return c.id


async def create_patient(session: AsyncSession, actor: CurrentUser, data: dict[str, Any]) -> Patient:
    branch = await branch_for(session, actor, data["branch_id"])
    if not (clean(data.get("name_en")) or clean(data.get("name_km"))):
        raise AppError(ErrorCode.VALIDATION_ERROR, "Give the name in Khmer or English", status_code=422)
    p = Patient(
        name_km=clean(data.get("name_km")), name_en=clean(data.get("name_en")), sex=data["sex"], dob=data.get("dob"),
        phone=_phone(data.get("phone")), customer_id=await _customer(session, data.get("customer_id")),
        home_branch_id=branch.id, chronic_conditions=clean(data.get("chronic_conditions")),
        notes=clean(data.get("notes")), created_by=actor.id, allergies=[], branches=[],
    )  # fmt: skip
    for a in data.get("allergies") or []:
        p.allergies.append(PatientAllergy(kind=a["kind"], value=clean(a["value"]), note=clean(a.get("note")),
                                          created_by=actor.id))  # fmt: skip
    p.branches.append(PatientBranch(branch_id=branch.id))
    session.add(p)
    await session.flush()
    _event(session, "patient.created", p)
    audit(session, actor, "patient.created", "patient", p.id, branch_id=branch.id,
          after={**p.safe_fields(), "allergies": [f"{a.kind}: {a.value}" for a in p.allergies]})  # fmt: skip
    await session.commit()
    return p


async def update_patient(
    session: AsyncSession, actor: CurrentUser, patient_id: UUID, data: dict[str, Any]
) -> Patient:
    p = await get_patient(session, actor, patient_id, lock=True)
    before = p.safe_fields()
    for f in ("name_km", "name_en", "chronic_conditions", "notes"):
        if data.get(f) is not None:
            setattr(p, f, clean(data[f]))
    if data.get("sex") is not None:
        p.sex = data["sex"]
    if "dob" in data:
        p.dob = data["dob"]
    if data.get("phone") is not None:
        p.phone = _phone(data["phone"])
    if "customer_id" in data:
        p.customer_id = await _customer(session, data["customer_id"])
    after = p.safe_fields()
    if after != before:
        p.version += 1
        _event(session, "patient.updated", p)
        old, new = changes(before, after)
        audit(
            session,
            actor,
            "patient.updated",
            "patient",
            p.id,
            branch_id=p.home_branch_id,
            before=old,
            after=new,
        )
    await session.commit()
    return p


async def set_active(
    session: AsyncSession, actor: CurrentUser, patient_id: UUID, active: bool, reason: str | None
) -> Patient:
    p = await get_patient(session, actor, patient_id, lock=True)
    if p.is_active != active:
        p.is_active = active
        p.version += 1
        action = "patient.activated" if active else "patient.deactivated"
        _event(session, action, p)
        audit(session, actor, action, "patient", p.id, branch_id=p.home_branch_id, before={"is_active": not active},
              after={"is_active": active, **({"reason": reason} if reason else {})})  # fmt: skip
        await session.commit()
    return p


async def add_allergy(
    session: AsyncSession, actor: CurrentUser, patient_id: UUID, data: dict[str, Any]
) -> Patient:
    p = await get_patient(session, actor, patient_id, lock=True)
    value = clean(data["value"])
    if any(a.kind == data["kind"] and a.value.casefold() == value.casefold() for a in p.active_allergies):
        raise AppError(ErrorCode.DUPLICATE_NAME, "This allergy is already recorded", status_code=409)
    p.allergies.append(
        PatientAllergy(kind=data["kind"], value=value, note=clean(data.get("note")), created_by=actor.id)
    )
    p.version += 1
    await session.flush()
    _event(session, "patient.updated", p)
    audit(session, actor, "patient.allergy_added", "patient", p.id, branch_id=p.home_branch_id,
          after={"allergy": f"{data['kind']}: {value}", "note": clean(data.get("note"))})  # fmt: skip
    await session.commit()
    return p


async def remove_allergy(
    session: AsyncSession, actor: CurrentUser, patient_id: UUID, allergy_id: UUID, reason: str
) -> Patient:
    p = await get_patient(session, actor, patient_id, lock=True)
    allergy = next((a for a in p.allergies if a.id == allergy_id and a.is_active), None)
    if allergy is None:
        raise not_found("Allergy")
    allergy.is_active = False
    p.version += 1
    _event(session, "patient.updated", p)
    audit(session, actor, "patient.allergy_removed", "patient", p.id, branch_id=p.home_branch_id,
          before={"allergy": f"{allergy.kind}: {allergy.value}"}, after={"reason": clean(reason)})  # fmt: skip
    await session.commit()
    return p


async def link_by_phone(
    session: AsyncSession, actor: CurrentUser, phone: str, branch_id: UUID
) -> list[Patient]:
    """Another branch finds an existing patient by the exact phone number; this
    is logged and links the branch, so the patient is visible there from now on."""
    branch = await branch_for(session, actor, branch_id)
    number = _phone(phone)
    if not number:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Give the full phone number", status_code=422)
    found = list(
        (
            await session.execute(select(Patient).where(Patient.phone == number, Patient.is_active.is_(True)))
        ).scalars()
    )
    for p in found:
        if await link_branch(session, p.id, branch.id):
            p.version += 1
            await session.refresh(p, attribute_names=["branches"])
            _event(session, "patient.updated", p)
        audit(session, actor, "patient.linked", "patient", p.id, branch_id=branch.id,
              after={"found_by": "phone", "branch": branch.code})  # fmt: skip
    await session.commit()
    return found
