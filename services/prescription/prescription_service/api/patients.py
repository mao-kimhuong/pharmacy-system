from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, requires

from ..db import db
from ..models import Doctor, Patient
from ..schemas.rx import (
    AllergyIn,
    DoctorCreate,
    DoctorOut,
    DoctorPage,
    DoctorUpdate,
    OptionalReason,
    PatientCreate,
    PatientLink,
    PatientOut,
    PatientPage,
    PatientSummary,
    PatientUpdate,
    ReasonRequest,
)
from ..services import doctors, patients

router = APIRouter()


@router.get("/patients", response_model=PatientPage, tags=["patients"])
async def search_patients(
    q: str | None = Query(default=None, max_length=100, description="Name (Khmer or English) or phone"),
    include_inactive: bool = False, page: int = Query(default=1, ge=1), size: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(requires("patients.view")), session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """Patients of your branches (home or linked). Another branch's patient: use /patients/link."""
    items, total = await patients.search(session, user, q, include_inactive, page, size)
    return {"items": items, "total": total, "page": page, "size": size}


@router.post("/patients", response_model=PatientOut, status_code=201, tags=["patients"])
async def create_patient(
    body: PatientCreate, user: CurrentUser = Depends(requires("patients.manage")),
    session: AsyncSession = Depends(db.session),
) -> Patient:  # fmt: skip
    return await patients.create_patient(session, user, body.model_dump())


@router.post("/patients/link", response_model=list[PatientSummary], tags=["patients"])
async def link_patient(
    body: PatientLink, user: CurrentUser = Depends(requires("patients.manage")),
    session: AsyncSession = Depends(db.session),
) -> list[Patient]:  # fmt: skip
    """Find a patient registered at another branch by the exact phone number. Logged;
    links your branch so the patient is visible here from now on."""
    return await patients.link_by_phone(session, user, body.phone, body.branch_id)


@router.get("/patients/{patient_id}", response_model=PatientOut, tags=["patients"])
async def get_patient(
    patient_id: UUID, user: CurrentUser = Depends(requires("patients.view")),
    session: AsyncSession = Depends(db.session),
) -> Patient:  # fmt: skip
    """The full record with allergies. Every view is written to the User Log."""
    return await patients.view_patient(session, user, patient_id)


@router.patch("/patients/{patient_id}", response_model=PatientOut, tags=["patients"])
async def update_patient(
    patient_id: UUID, body: PatientUpdate, user: CurrentUser = Depends(requires("patients.manage")),
    session: AsyncSession = Depends(db.session),
) -> Patient:  # fmt: skip
    return await patients.update_patient(session, user, patient_id, body.model_dump(exclude_unset=True))


@router.post("/patients/{patient_id}/deactivate", response_model=PatientOut, tags=["patients"])
async def deactivate_patient(
    patient_id: UUID, body: ReasonRequest, user: CurrentUser = Depends(requires("patients.manage")),
    session: AsyncSession = Depends(db.session),
) -> Patient:  # fmt: skip
    return await patients.set_active(session, user, patient_id, False, body.reason)


@router.post("/patients/{patient_id}/activate", response_model=PatientOut, tags=["patients"])
async def activate_patient(
    patient_id: UUID, body: OptionalReason | None = None, user: CurrentUser = Depends(requires("patients.manage")),
    session: AsyncSession = Depends(db.session),
) -> Patient:  # fmt: skip
    return await patients.set_active(session, user, patient_id, True, body.reason if body else None)


@router.post(
    "/patients/{patient_id}/allergies", response_model=PatientOut, status_code=201, tags=["patients"]
)
async def add_allergy(
    patient_id: UUID, body: AllergyIn, user: CurrentUser = Depends(requires("patients.manage")),
    session: AsyncSession = Depends(db.session),
) -> Patient:  # fmt: skip
    return await patients.add_allergy(session, user, patient_id, body.model_dump())


@router.post(
    "/patients/{patient_id}/allergies/{allergy_id}/remove", response_model=PatientOut, tags=["patients"]
)
async def remove_allergy(
    patient_id: UUID, allergy_id: UUID, body: ReasonRequest,
    user: CurrentUser = Depends(requires("patients.manage")), session: AsyncSession = Depends(db.session),
) -> Patient:  # fmt: skip
    """Allergies are never deleted: deactivated with a reason (logged)."""
    return await patients.remove_allergy(session, user, patient_id, allergy_id, body.reason)


# ---------------------------------------------------------------- doctors


@router.get("/doctors", response_model=DoctorPage, tags=["doctors"])
async def list_doctors(
    q: str | None = Query(default=None, max_length=100), include_inactive: bool = False,
    page: int = Query(default=1, ge=1), size: int = Query(default=50, ge=1, le=200),
    _: CurrentUser = Depends(requires("prescriptions.view")), session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    items, total = await doctors.list_doctors(session, q, include_inactive, page, size)
    return {"items": items, "total": total, "page": page, "size": size}


@router.post("/doctors", response_model=DoctorOut, status_code=201, tags=["doctors"])
async def create_doctor(
    body: DoctorCreate, user: CurrentUser = Depends(requires("prescriptions.manage")),
    session: AsyncSession = Depends(db.session),
) -> Doctor:  # fmt: skip
    return await doctors.create_doctor(session, user, body.model_dump())


@router.get("/doctors/{doctor_id}", response_model=DoctorOut, tags=["doctors"])
async def get_doctor(
    doctor_id: UUID, _: CurrentUser = Depends(requires("prescriptions.view")),
    session: AsyncSession = Depends(db.session),
) -> Doctor:  # fmt: skip
    return await doctors.get_doctor(session, doctor_id)


@router.patch("/doctors/{doctor_id}", response_model=DoctorOut, tags=["doctors"])
async def update_doctor(
    doctor_id: UUID, body: DoctorUpdate, user: CurrentUser = Depends(requires("prescriptions.manage")),
    session: AsyncSession = Depends(db.session),
) -> Doctor:  # fmt: skip
    return await doctors.update_doctor(session, user, doctor_id, body.model_dump(exclude_unset=True))


@router.post("/doctors/{doctor_id}/deactivate", response_model=DoctorOut, tags=["doctors"])
async def deactivate_doctor(
    doctor_id: UUID, body: ReasonRequest, user: CurrentUser = Depends(requires("prescriptions.manage")),
    session: AsyncSession = Depends(db.session),
) -> Doctor:  # fmt: skip
    return await doctors.set_active(session, user, doctor_id, False, body.reason)


@router.post("/doctors/{doctor_id}/activate", response_model=DoctorOut, tags=["doctors"])
async def activate_doctor(
    doctor_id: UUID, body: OptionalReason | None = None,
    user: CurrentUser = Depends(requires("prescriptions.manage")), session: AsyncSession = Depends(db.session),
) -> Doctor:  # fmt: skip
    return await doctors.set_active(session, user, doctor_id, True, body.reason if body else None)
