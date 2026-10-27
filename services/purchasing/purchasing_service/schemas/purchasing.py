from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Money = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2, examples=["120.50"])]
UnitCost = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=4, examples=["4.2500"])]
Qty = Annotated[int, Field(ge=1, le=1_000_000)]


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=255)


# ---------------------------------------------------------------- suppliers


class GroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name_en: str
    name_km: str
    is_active: bool


class GroupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_en: str = Field(min_length=1, max_length=120)
    name_km: str = Field(default="", max_length=120)


class GroupUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_en: str | None = Field(default=None, min_length=1, max_length=120)
    name_km: str | None = Field(default=None, max_length=120)


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    name_km: str
    phone: str
    address: str
    payment_terms_days: int
    group: GroupOut | None
    is_active: bool
    created_at: datetime


class SupplierPage(BaseModel):
    items: list[SupplierOut]
    total: int
    page: int
    size: int


class SupplierCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=2, max_length=20, examples=["DKSH"])
    name: str = Field(min_length=1, max_length=160, examples=["DKSH Cambodia"])
    name_km: str = Field(default="", max_length=160)
    phone: str = Field(default="", max_length=32)
    address: str = Field(default="", max_length=255)
    payment_terms_days: int = Field(default=0, ge=0, le=365)
    group_id: UUID | None = None


class SupplierUpdate(BaseModel):
    """The code cannot be changed."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=160)
    name_km: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=255)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    group_id: UUID | None = None


# ---------------------------------------------------------------- purchase orders


class POLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medicine_id: UUID
    pack_unit_id: UUID
    qty: Qty = Field(description="In the pack unit, e.g. 10 boxes")
    unit_cost: UnitCost = Field(description="USD per pack unit")


class POCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    supplier_id: UUID
    note: str = Field(default="", max_length=1000)
    expected_on: date | None = None
    lines: list[POLineIn] = Field(min_length=1, max_length=200)


class POUpdate(BaseModel):
    """Draft only. `lines` replaces all lines."""

    model_config = ConfigDict(extra="forbid")

    supplier_id: UUID | None = None
    note: str | None = Field(default=None, max_length=1000)
    expected_on: date | None = None
    lines: list[POLineIn] | None = Field(default=None, min_length=1, max_length=200)


class POLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_no: int
    medicine_id: UUID
    pack_unit_id: UUID
    qty: int
    qty_base: int
    qty_in_base: int
    qty_received_base: int
    unit_cost: Decimal | None = Field(default=None, description="Only for users who buy, pay or see cost")
    line_total: Decimal | None = None


class POOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    number: str
    branch_id: UUID
    supplier: SupplierOut
    status: Literal["draft", "sent", "partially_received", "received", "cancelled"]
    note: str
    expected_on: date | None
    sent_at: datetime | None
    cancel_reason: str | None
    version: int
    lines: list[POLineOut]
    total: Decimal | None = None
    created_at: datetime


class POPage(BaseModel):
    items: list[POOut]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------- receiving


class ReceiveLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    po_line_id: UUID
    lot_no: str = Field(min_length=1, max_length=40)
    expiry_date: date
    qty: Qty = Field(description="In the PO line's pack unit")
    unit_cost: UnitCost | None = Field(default=None, description="Default: the PO price")


class ReceiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_invoice_no: str = Field(default="", max_length=60)
    allow_over: bool = False
    lines: list[ReceiveLineIn] = Field(min_length=1, max_length=400)


class ReceiptLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_no: int
    po_line_id: UUID
    medicine_id: UUID
    pack_unit_id: UUID
    lot_no: str
    expiry_date: date
    qty: int
    qty_base: int
    short_expiry: bool
    over_received: bool
    controlled_schedule: str | None
    unit_cost: Decimal | None = None
    cost_per_base: Decimal | None = None
    line_total: Decimal | None = None


class ReceiptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    number: str
    po_id: UUID
    branch_id: UUID
    supplier_id: UUID
    supplier_invoice_no: str
    received_at: datetime
    due_on: date
    status: Literal["open", "paid"]
    lines: list[ReceiptLineOut]
    total: Decimal | None = None
    paid: Decimal | None = None
    balance: Decimal | None = None


class ReceiptPage(BaseModel):
    items: list[ReceiptOut]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------- payments


class PaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_id: UUID
    branch_id: UUID
    method: Literal["cash", "bank", "ABA", "KHQR"]
    amount: Money
    reference: str = Field(default="", max_length=120)
    paid_on: date | None = None


class AllocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    receipt_id: UUID
    amount: Decimal
    reversed: bool


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    number: str
    supplier_id: UUID
    branch_id: UUID
    method: str
    amount: Decimal
    reference: str
    paid_on: date
    status: Literal["posted", "cancelled"]
    cancel_reason: str | None
    allocations: list[AllocationOut]
    created_at: datetime


class PaymentPage(BaseModel):
    items: list[PaymentOut]
    total: int
    page: int
    size: int


class BranchBalance(BaseModel):
    branch_id: UUID
    owed: Decimal
    overdue: Decimal


class BalanceOut(BaseModel):
    supplier_id: UUID
    owed: Decimal
    overdue: Decimal
    branches: list[BranchBalance]


class StatementEntry(BaseModel):
    on: date
    kind: Literal["receipt", "payment"]
    number: str
    branch_id: UUID
    debit: Decimal
    credit: Decimal
    due_on: date | None
    balance: Decimal


class StatementOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    supplier_id: UUID
    supplier: str
    date_from: date | None = Field(alias="from")
    date_to: date | None = Field(alias="to")
    opening_balance: Decimal
    closing_balance: Decimal
    entries: list[StatementEntry]
