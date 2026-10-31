from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Money = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2, examples=["12.50"])]
Limit = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2, examples=["200.00"])]
Pct = Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=255)


class GroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name_en: str
    name_km: str
    default_discount_pct: Decimal
    is_active: bool


class GroupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_en: str = Field(min_length=1, max_length=120, examples=["Clinic"])
    name_km: str = Field(default="", max_length=120)
    default_discount_pct: Pct = Decimal("0")


class GroupUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_en: str | None = Field(default=None, min_length=1, max_length=120)
    name_km: str | None = Field(default=None, max_length=120)
    default_discount_pct: Pct | None = None


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    phone: str
    name: str
    name_km: str
    group: GroupOut | None
    credit_limit: Decimal
    note: str
    is_active: bool
    created_at: datetime
    balance: Decimal | None = None
    available_credit: Decimal | None = None


class CustomerPage(BaseModel):
    items: list[CustomerOut]
    total: int
    page: int
    size: int


class CustomerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=6, max_length=32, examples=["012 345 678"])
    name: str = Field(min_length=1, max_length=160)
    name_km: str = Field(default="", max_length=160)
    group_id: UUID | None = None
    credit_limit: Limit = Field(default=Decimal("0"), description="Above 0 needs customers.credit_limit")
    note: str = Field(default="", max_length=1000)


class CustomerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str | None = Field(default=None, min_length=6, max_length=32)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    name_km: str | None = Field(default=None, max_length=160)
    group_id: UUID | None = None
    credit_limit: Limit | None = Field(default=None, description="Changing it needs customers.credit_limit")
    note: str | None = Field(default=None, max_length=1000)


class DebtOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    invoice_id: UUID
    invoice_no: str
    branch_id: UUID
    amount: Decimal
    paid: Decimal
    reduced: Decimal
    due: Decimal
    created_at: datetime


class PaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: UUID
    branch_id: UUID
    method: Literal["cash", "card", "ABA", "KHQR"]
    amount: Money
    reference: str = Field(default="", max_length=120)
    paid_on: date | None = None


class AllocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    invoice_no: str
    amount: Decimal
    reversed: bool


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    number: str
    customer_id: UUID
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


class StatementEntry(BaseModel):
    on: date
    kind: str
    document_no: str
    branch_id: UUID | None
    debit: Decimal
    credit: Decimal
    reason: str
    balance: Decimal


class StatementOut(BaseModel):
    customer_id: UUID
    customer: str
    date_from: date | None = Field(alias="from")
    date_to: date | None = Field(alias="to")
    opening_balance: Decimal
    closing_balance: Decimal
    balance: Decimal
    entries: list[StatementEntry]


# ---------------------------------------------------------------- internal


class ChargeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_id: UUID
    invoice_no: str = Field(default="", max_length=40)
    customer_id: UUID
    branch_id: UUID
    amount: Money


class ReverseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_id: UUID
    customer_id: UUID
    branch_id: UUID | None = None
    kind: Literal["cancel", "return"]
    ref_id: str | None = Field(default=None, max_length=80, description="The return id (kind=return)")
    amount: Money | None = Field(default=None, description="Credit note amount (kind=return)")
    document_no: str = Field(default="", max_length=40)
    reason: str = Field(default="", max_length=255)


class CreditResult(BaseModel):
    entry_id: UUID | None
    amount: Decimal
    balance_after: Decimal


class NumberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_id: UUID
    invoice_no: str = Field(min_length=1, max_length=40)


# ---------------------------------------------------------------- deposits (S7)


class DepositTake(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: str = Field(min_length=1, max_length=80)
    document_no: str = Field(default="", max_length=40)
    customer_id: UUID
    branch_id: UUID
    method: Literal["cash", "card", "ABA", "KHQR"]
    currency: Literal["USD", "KHR"] = "USD"
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2, description="USD")


class DepositUse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_id: UUID
    invoice_no: str = Field(default="", max_length=40)
    customer_id: UUID | None = None
    amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    reason: str = Field(default="", max_length=255)


class DepositSettle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["keep_as_credit", "refund", "forfeit"]
    reason: str = Field(default="", max_length=255)


class DepositOut(BaseModel):
    deposit_id: UUID
    ref: str
    document_no: str
    amount: Decimal
    used: Decimal
    remaining: Decimal
    status: str
    method: str
    currency: str
