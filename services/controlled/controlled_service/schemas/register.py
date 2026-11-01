from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Token = Field(default=None, max_length=200)


class EntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    seq: int
    branch_id: UUID
    medicine_id: UUID
    batch_id: UUID | None
    lot_no: str
    expiry_date: date | None
    entry_type: str
    qty_base: int
    balance_after: int
    ref_type: str
    ref_id: str
    prescription_number: str
    patient_id: UUID | None
    patient_name: str
    patient_id_document: str
    actor_id: UUID | None
    actor_name: str
    witness_id: UUID | None
    witness_name: str
    reason: str
    corrects_entry_id: UUID | None
    occurred_at: datetime
    entry_hash: str


class ChainOut(BaseModel):
    medicine_id: UUID
    valid: bool
    entries: int
    first_bad_entry_id: UUID | None
    problem: str


class MedicineRef(BaseModel):
    id: UUID
    sku: str
    name: str
    name_km: str
    strength: str
    base_unit: str
    schedule: str | None


class RegisterOut(BaseModel):
    branch_id: UUID
    branch_name_en: str
    branch_name_km: str
    chain_valid: bool
    chains: list[ChainOut]
    medicines: list[MedicineRef]
    entries: list[EntryOut]


class AdjustIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    batch_id: UUID
    kind: Literal["adjust_in", "adjust_out", "destroy"]
    qty_base: int = Field(ge=1, le=1_000_000)
    reason: str = Field(min_length=1, max_length=255)
    destruction_method: str = Field(default="", max_length=120)
    pin_token: str | None = Token
    witness_token: str | None = Token


class AdjustOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    branch_id: UUID
    batch_id: UUID
    kind: str
    qty_base: int
    reason: str
    destruction_method: str
    actor_id: UUID
    witness_id: UUID
    witness_name: str
    movement_id: UUID | None


class CorrectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    corrects_entry_id: UUID
    qty_base: int = Field(ge=-1_000_000, le=1_000_000, description="Signed; 0 for a note only")
    reason: str = Field(min_length=1, max_length=255)
    pin_token: str | None = Token
    witness_token: str | None = Token


class DiscrepancyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    branch_id: UUID
    medicine_id: UUID
    batch_id: UUID
    lot_no: str
    register_qty: int
    stock_qty: int
    difference: int
    status: str
    found_at: datetime
    resolved_at: datetime | None
    resolved_by: UUID | None
    witness_id: UUID | None
    reason: str
    note: str
    correction_entry_id: UUID | None


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=255)
    note: str = Field(default="", max_length=1000)
    correct_register: bool = Field(default=False, description="Add a correction entry: register = stock")
    pin_token: str | None = Token
    witness_token: str | None = Token


class VerifyOut(BaseModel):
    valid: bool
    chains: list[ChainOut]


class RegisterQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    medicine_id: UUID | None = None
    date_from: date | None = None
    date_to: date | None = None


class EntryDetail(BaseModel):
    """One register entry: its neighbours in the chain and whether its hash still matches."""

    entry: EntryOut
    prev_entry_id: UUID | None
    next_entry_id: UUID | None
    hash_valid: bool = Field(description="sha256(prev_hash + the entry) equals the stored hash, and prev_hash is "
                             "the previous entry's hash")  # fmt: skip
    corrected_by: list[UUID] = Field(description="Correction entries pointing at this one")
