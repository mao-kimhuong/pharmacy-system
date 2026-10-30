from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Phone = Annotated[str, Field(max_length=30, examples=["012 345 678"])]
Text = Annotated[str, Field(max_length=2000)]
Status = Literal["draft", "active", "partly_dispensed", "fully_dispensed", "expired", "cancelled"]


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=255)


class OptionalReason(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=255)


# ---------------------------------------------------------------- patients


class AllergyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["ingredient", "class"] = Field(
        description="An active ingredient or a drug class, as in the catalog"
    )
    value: str = Field(min_length=1, max_length=80, examples=["Amoxicillin", "penicillins"])
    note: str = Field(default="", max_length=255, examples=["rash in 2024"])


class AllergyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    value: str
    note: str
    is_active: bool
    created_at: datetime


class PatientCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID = Field(description="Home branch")
    name_km: str = Field(default="", max_length=160)
    name_en: str = Field(default="", max_length=160)
    sex: Literal["female", "male", "other"]
    dob: date | None = None
    phone: Phone | None = None
    customer_id: UUID | None = None
    chronic_conditions: Text = ""
    notes: Text = ""
    allergies: list[AllergyIn] = Field(default_factory=list, max_length=30)


class PatientUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_km: str | None = Field(default=None, max_length=160)
    name_en: str | None = Field(default=None, max_length=160)
    sex: Literal["female", "male", "other"] | None = None
    dob: date | None = None
    phone: Phone | None = None
    customer_id: UUID | None = None
    chronic_conditions: Text | None = None
    notes: Text | None = None


class PatientSummary(BaseModel):
    """In lists: no allergies, conditions or notes (open the record for those; logged)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name_km: str
    name_en: str
    sex: str
    dob: date | None
    phone: str
    home_branch_id: UUID
    is_active: bool


class PatientOut(PatientSummary):
    customer_id: UUID | None
    chronic_conditions: str
    notes: str
    branch_ids: list[UUID]
    allergies: list[AllergyOut]
    version: int
    created_at: datetime
    updated_at: datetime


class PatientPage(BaseModel):
    items: list[PatientSummary]
    total: int
    page: int
    size: int


class PatientLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    phone: Phone


# ---------------------------------------------------------------- doctors


class DoctorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    licence_no: str = Field(min_length=1, max_length=60)
    specialty: str = Field(default="", max_length=120)
    clinic: str = Field(default="", max_length=160)
    phone: Phone | None = None


class DoctorUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=160)
    licence_no: str | None = Field(default=None, min_length=1, max_length=60)
    specialty: str | None = Field(default=None, max_length=120)
    clinic: str | None = Field(default=None, max_length=160)
    phone: Phone | None = None


class DoctorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    licence_no: str
    specialty: str
    clinic: str
    phone: str
    is_active: bool
    created_at: datetime


class DoctorPage(BaseModel):
    items: list[DoctorOut]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------- prescriptions


class RxItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medicine_id: UUID
    qty_base: int = Field(ge=1, le=100_000, description="One fill, in the medicine's base unit")
    dosage: str = Field(default="", max_length=160, examples=["1 tablet"])
    frequency: str = Field(default="", max_length=160, examples=["3 times a day after meals"])
    duration_days: int | None = Field(default=None, ge=1, le=3650)
    repeats_allowed: int = Field(default=0, ge=0, le=12, description="Refills after the first fill")


class RxCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    patient_id: UUID
    doctor_id: UUID
    rx_no: str = Field(default="", max_length=60, description="The number on the doctor's paper prescription")
    issued_on: date
    valid_until: date | None = Field(
        default=None, description="Left out: issued_on + the branch's rx_valid_days"
    )
    notes: Text = ""
    items: list[RxItemIn] = Field(min_length=1, max_length=30)


class RxUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doctor_id: UUID | None = None
    rx_no: str | None = Field(default=None, max_length=60)
    issued_on: date | None = None
    valid_until: date | None = None
    notes: Text | None = None
    items: list[RxItemIn] | None = Field(default=None, min_length=1, max_length=30)


class RxItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_no: int
    medicine_id: UUID
    qty_base: int
    dosage: str
    frequency: str
    duration_days: int | None
    repeats_allowed: int
    repeats_used: int
    allowed_base: int
    dispensed_base: int
    held_base: int
    remaining_base: int


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    original_filename: str
    content_type: str
    size_bytes: int
    uploaded_by: UUID | None
    created_at: datetime


class PersonRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str = ""


class PatientRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name_km: str
    name_en: str


class RxOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    number: str
    rx_no: str
    branch_id: UUID
    patient: PatientRef
    doctor: PersonRef
    issued_on: date
    valid_until: date
    status: Status
    notes: str
    activated_at: datetime | None
    cancel_reason: str | None
    cancelled_at: datetime | None
    version: int
    items: list[RxItemOut]
    attachments: list[AttachmentOut]
    created_at: datetime


class RxSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    number: str
    rx_no: str
    branch_id: UUID
    patient: PatientRef
    doctor: PersonRef
    issued_on: date
    valid_until: date
    status: Status
    created_at: datetime


class RxPage(BaseModel):
    items: list[RxSummary]
    total: int
    page: int
    size: int


class RemainingItem(BaseModel):
    rx_item_id: UUID
    line_no: int
    medicine_id: UUID
    name: str
    base_unit: str
    fill_base: int
    remaining_base: int
    can_dispense_now: int = Field(description="min(remaining, one fill); 0 when the Rx cannot be dispensed")
    repeats_allowed: int
    repeats_used: int
    dosage: str
    frequency: str
    duration_days: int | None


class Remaining(BaseModel):
    prescription_id: UUID
    number: str
    status: Status
    valid_until: date
    dispensable: bool
    patient: PatientRef
    items: list[RemainingItem]


# ---------------------------------------------------------------- internal (sale saga)


class HoldLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_no: int = Field(ge=1)
    rx_item_id: UUID
    medicine_id: UUID
    qty_base: int = Field(ge=1)
    allergy_override_reason: str | None = Field(default=None, max_length=255)
    acknowledge_warnings: bool = False


class HoldRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_id: UUID
    branch_id: UUID
    lines: list[HoldLine] = Field(min_length=1, max_length=100)


class Warning(BaseModel):
    kind: Literal["allergy", "duplicate_therapy"]
    value: str
    en: str
    km: str
    prescription: str | None = None


class HeldLine(BaseModel):
    line_no: int
    rx_item_id: UUID
    prescription_id: UUID
    prescription_number: str
    patient_id: UUID
    patient_name_en: str
    patient_name_km: str
    doctor_name: str
    dosage: str
    frequency: str
    duration_days: int | None
    remaining_after: int
    warnings: list[Warning]


class HoldOut(BaseModel):
    invoice_id: UUID
    lines: list[HeldLine]


class ReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_id: UUID


class ReleaseOut(BaseModel):
    invoice_id: UUID
    released: int
