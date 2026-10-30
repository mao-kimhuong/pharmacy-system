from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

UnitCost = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=4, examples=["4.25"])]
CostNote = "Only for users with finance.cost_profit"


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=255)


class PackQty(BaseModel):
    pack_unit: str
    qty: int


class BatchRow(BaseModel):
    batch_id: UUID
    lot_no: str
    expiry_date: date
    days_to_expiry: int
    status: str
    received_at: datetime
    supplier_id: UUID | None
    qty_on_hand: int
    qty_reserved: int
    qty_quarantined: int
    qty_available: int = Field(description="Sellable now: active, not expired, not reserved or quarantined")
    cost_per_base: Decimal | None = Field(default=None, description=CostNote)
    value: Decimal | None = Field(default=None, description=CostNote)


class StockItem(BaseModel):
    branch_id: UUID
    medicine_id: UUID
    sku: str
    name: str
    name_km: str
    base_unit: str
    controlled_schedule: str | None
    qty_on_hand: int
    qty_reserved: int
    qty_quarantined: int
    qty_available: int
    on_hand_in_packs: list[PackQty]
    available_in_packs: list[PackQty]
    stock_value: Decimal | None = Field(default=None, description=CostNote)
    batches: list[BatchRow] = Field(description="FEFO: earliest expiry first")


class StockPage(BaseModel):
    items: list[StockItem]
    total: int
    page: int
    size: int


class BatchItem(BatchRow):
    branch_id: UUID
    medicine_id: UUID
    sku: str
    name: str
    on_hand_in_packs: list[PackQty]


class BatchPage(BaseModel):
    items: list[BatchItem]
    total: int
    page: int
    size: int


class MovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    branch_id: UUID
    batch_id: UUID
    medicine_id: UUID
    type: str
    qty_base: int
    qty_after: int
    ref_type: str
    ref_id: str
    reason: str
    created_by: UUID | None
    created_at: datetime


class MovementPage(BaseModel):
    items: list[MovementOut]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------- stock-in


class StockInLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medicine_id: UUID
    pack_unit_id: UUID
    lot_no: str = Field(min_length=1, max_length=40)
    expiry_date: date
    qty: int = Field(ge=1, le=1_000_000, description="In the pack unit")
    unit_cost: UnitCost = Field(description="USD per pack unit")


class StockInRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    reason: str = Field(min_length=1, max_length=255, examples=["Donation from clinic"])
    supplier_id: UUID | None = None
    lines: list[StockInLineIn] = Field(min_length=1, max_length=200)


class StockInLineOut(BaseModel):
    line_no: int
    medicine_id: UUID
    sku: str
    pack_unit_id: UUID
    pack_unit: str
    qty: int
    qty_base: int
    batch_id: UUID
    lot_no: str
    expiry_date: date
    short_expiry: bool
    qty_after: int
    unit_cost: Decimal | None = Field(default=None, description=CostNote)
    cost_per_base: Decimal | None = Field(default=None, description=CostNote)


class StockInOut(BaseModel):
    id: UUID
    branch_id: UUID
    supplier_id: UUID | None
    reason: str
    created_at: datetime
    lines: list[StockInLineOut]


# ---------------------------------------------------------------- opening stock


class OpeningLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medicine_id: UUID
    pack_unit_id: UUID
    lot_no: str = Field(max_length=40)
    expiry_date: date
    qty: int = Field(ge=1, le=1_000_000)
    unit_cost: UnitCost


class OpeningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    lines: list[OpeningLineIn] = Field(min_length=1, max_length=5000)


class OpeningLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    line_no: int
    data: dict
    medicine_id: UUID | None
    pack_unit_id: UUID | None
    lot_no: str
    expiry_date: date | None
    qty: int | None
    qty_base: int | None
    short_expiry: bool
    errors: list[dict]
    unit_cost: Decimal | None = Field(default=None, description=CostNote)
    cost_per_base: Decimal | None = Field(default=None, description=CostNote)


class OpeningOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    branch_id: UUID
    status: Literal["validated", "has_errors", "committed"]
    source: str
    file_name: str
    total_lines: int
    error_lines: int
    created_at: datetime
    committed_at: datetime | None
    lines: list[OpeningLineOut]


class OpeningPage(BaseModel):
    items: list[OpeningOut]
    total: int
    page: int
    size: int


class LockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    branch_id: UUID
    locked: bool
    opening_id: UUID | None
    locked_at: datetime | None
    unlocked_at: datetime | None
    unlock_reason: str | None


class QuarantineRelease(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    batch_id: UUID
    qty_base: int = Field(ge=1, le=10_000_000)
    reason: str = Field(min_length=1, max_length=255, examples=["Checked: sealed and undamaged"])


class QuarantineReleaseOut(BaseModel):
    branch_id: UUID
    batch_id: UUID
    qty_on_hand: int
    qty_quarantined: int
    released: int


# ---------------------------------------------------------------- internal (sale saga)


class ReserveLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_no: int = Field(ge=1)
    medicine_id: UUID
    qty_base: int = Field(ge=1, le=10_000_000)
    batch_id: UUID | None = Field(default=None, description="Pharmacist's batch override")
    meta: dict[str, Any] | None = Field(default=None, description="Controlled lines: Rx, patient, pharmacist")


class ReserveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref_type: Literal["invoice"] = "invoice"
    ref_id: str = Field(min_length=1, max_length=80)
    branch_id: UUID
    lines: list[ReserveLine] = Field(min_length=1, max_length=200)


class ReservedBatch(BaseModel):
    line_no: int
    medicine_id: UUID
    batch_id: UUID
    lot_no: str
    expiry_date: date
    qty_base: int
    cost_per_base: Decimal
    overridden: bool


class ReservationOut(BaseModel):
    id: UUID
    ref_type: str
    ref_id: str
    branch_id: UUID
    status: str
    lines: list[ReservedBatch]


class ReverseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="", max_length=255)


class ReleaseByRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref_type: Literal["invoice"] = "invoice"
    ref_id: str = Field(min_length=1, max_length=80)


class ReturnItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref_id: str = Field(min_length=1, max_length=80, description="Unique per returned line and batch")
    batch_id: UUID
    qty_base: int = Field(ge=1, le=10_000_000)
    meta: dict[str, Any] | None = Field(default=None, description="Controlled lines: Rx / patient refs")


class ReturnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    to: Literal["stock", "quarantine"]
    reason: str = Field(default="", max_length=255)
    items: list[ReturnItem] = Field(min_length=1, max_length=400)


class ReturnBooked(BaseModel):
    ref_id: str
    batch_id: UUID
    qty_base: int
    booked: bool


# ---------------------------------------------------------------- S5: shelf locations, shrinkage


class LocationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    medicine_id: UUID
    code: str = Field(default="", max_length=12, examples=["A3"], description="Empty: no location")


class LocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    branch_id: UUID
    medicine_id: UUID
    code: str


class LocationRow(LocationOut):
    sku: str
    name: str


class ShrinkageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    batch_id: UUID
    qty_base: int = Field(ge=1, le=10_000_000)
    reason: Literal["expired", "damaged", "broken", "lost_theft", "recalled"]
    note: str = Field(default="", max_length=1000)
    destruction_method: str = Field(default="", max_length=120, description="Required for controlled medicines")
    pin_token: str | None = Field(default=None, max_length=200, description="Controlled: your PIN (auth /pin/verify)")
    witness_token: str | None = Field(default=None, max_length=200, description="Controlled: the witness (/pin/witness)")


class ShrinkageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    number: str
    branch_id: UUID
    batch_id: UUID
    medicine_id: UUID
    lot_no: str = ""
    qty_base: int
    reason: str
    note: str
    destruction_method: str
    value: Decimal | None = Field(default=None, description="Only with finance.cost_profit")
    status: str
    is_controlled: bool
    witness_id: UUID | None
    witness_name: str
    has_photo: bool = False
    created_by: UUID | None
    decided_by: UUID | None
    decided_at: datetime | None
    reject_reason: str | None
    created_at: datetime


class ShrinkagePage(BaseModel):
    items: list[ShrinkageOut]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------- S5: internal (stockcount, controlled)


class SnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    scope: Literal["full", "category", "location", "controlled"] = "full"
    category_id: UUID | None = None
    location: str | None = Field(default=None, max_length=12)


class BatchUntil(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: UUID
    until: datetime


class MovementsSince(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    after_seq: int = Field(ge=0)
    batch_ids: list[UUID] | None = Field(default=None, max_length=20_000)
    until: list[BatchUntil] | None = Field(default=None, max_length=20_000)


class ControlledStockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID | None = None


class ControlledMovement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    branch_id: UUID
    batch_id: UUID
    kind: Literal["adjust_in", "adjust_out", "destroy"]
    qty_base: int = Field(ge=1, le=10_000_000)
    reason: str = Field(min_length=1, max_length=255)
    meta: dict[str, Any] = Field(default_factory=dict)
