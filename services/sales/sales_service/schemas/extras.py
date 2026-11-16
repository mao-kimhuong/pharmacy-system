from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .sales import LineIn, PaymentIn


class CartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    customer_id: UUID | None = None
    note: str = Field(default="", max_length=255)
    lines: list[LineIn] = Field(min_length=1, max_length=200)


class PricedLineOut(BaseModel):
    line_no: int
    medicine_id: UUID
    pack_unit_id: UUID
    sku: str
    name: str
    pack_unit: str
    qty: int
    unit_price: Decimal
    line_total: Decimal
    promo_discount: Decimal
    promotion_ids: list[str]
    manual_discount: Decimal
    net: Decimal
    is_hamper: bool = False
    is_rx_only: bool = False


class PricedCart(BaseModel):
    lines: list[PricedLineOut]
    subtotal: Decimal
    discount: Decimal
    total: Decimal


class CartOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    number: str
    branch_id: UUID
    customer_id: UUID | None
    note: str
    priced: list[dict[str, Any]]
    total: Decimal
    status: str
    created_by: UUID
    created_at: datetime
    resumed_by: UUID | None
    resumed_at: datetime | None
    expired_at: datetime | None


class ResumedCart(BaseModel):
    cart_id: UUID
    number: str
    customer_id: UUID | None
    note: str
    lines: list[dict[str, Any]]
    total: Decimal
    changes: list[dict[str, Any]] = Field(
        description="What changed since parking: price, promotion, discount, stock"
    )


class TemplateLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medicine_id: UUID
    pack_unit_id: UUID
    qty: int = Field(ge=1, le=100_000)


class TemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    branch_id: UUID
    customer_id: UUID | None = Field(
        default=None, description="A customer's own basket; empty = the branch's"
    )
    note: str = Field(default="", max_length=255)
    lines: list[TemplateLineIn] = Field(min_length=1, max_length=200)


class TemplateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    note: str | None = Field(default=None, max_length=255)
    lines: list[TemplateLineIn] | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None


class TemplateLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    line_no: int
    medicine_id: UUID
    pack_unit_id: UUID
    qty: int


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    branch_id: UUID
    customer_id: UUID | None
    note: str
    is_active: bool
    lines: list[TemplateLineOut]


class LoadedTemplate(BaseModel):
    template_id: UUID
    name: str
    customer_id: UUID | None
    lines: list[PricedLineOut]
    total: Decimal


class QuoteLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medicine_id: UUID
    pack_unit_id: UUID
    qty: int = Field(ge=1, le=100_000)


class QuoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    customer_id: UUID
    note: str = Field(default="", max_length=500)
    valid_until: date | None = Field(default=None, description="The quoted prices; 7 days by default")
    lines: list[QuoteLineIn] = Field(min_length=1, max_length=200)


class DepositIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["cash", "card", "ABA", "KHQR"]
    currency: Literal["USD", "KHR"] = "USD"
    amount: Decimal = Field(gt=0, max_digits=16, decimal_places=2)


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reserve: bool = Field(default=False, description="Hold the stock (FEFO) for the order")
    reserve_days: int = Field(default=3, ge=1, le=14)
    deposit: DepositIn | None = None


class OrderInvoiceLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_line_id: UUID
    qty: int = Field(ge=1, le=100_000, description="In the order line's pack unit")
    rx_item_id: UUID | None = None
    allergy_override_reason: str | None = Field(default=None, max_length=255)
    acknowledge_warnings: bool = False
    patient_id_document: str | None = Field(default=None, min_length=3, max_length=40)
    discount_pct: Decimal | None = Field(default=None, gt=0, le=100, decimal_places=2)
    discount_amount: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    batch_id: UUID | None = None
    override_reason: str | None = Field(default=None, max_length=255)


class OrderInvoiceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lines: list[OrderInvoiceLine] = Field(min_length=1, max_length=200)
    payments: list[PaymentIn] = Field(min_length=1, max_length=10)
    change_in: Literal["USD", "KHR", "USD_KHR"] = "USD_KHR"
    note: str = Field(default="", max_length=500)
    pin_token: str | None = Field(default=None, max_length=200)
    discount_approval_token: str | None = Field(default=None, max_length=200)


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=255)


class OrderLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_no: int
    medicine_id: UUID
    pack_unit_id: UUID
    sku: str
    name: str
    pack_unit: str
    qty: int
    qty_invoiced: int
    qty_open: int
    unit_price: Decimal
    line_total: Decimal
    promo_discount: Decimal
    is_rx_only: bool


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    number: str
    branch_id: UUID
    customer_id: UUID
    status: str
    note: str
    valid_until: date | None
    reserve_until: datetime | None
    reservation_released_at: datetime | None
    deposit_id: UUID | None
    deposit_usd: Decimal
    subtotal: Decimal
    discount: Decimal
    total: Decimal
    cancel_reason: str | None
    ready_at: datetime | None = None
    lines: list[OrderLineOut]
    created_at: datetime


class RuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    kind: Literal["percent", "per_unit"]
    value: Decimal = Field(
        gt=0, max_digits=14, decimal_places=4, description="% of net, or USD per base unit"
    )
    scope: Literal["all", "medicine", "category", "brand"]
    target_id: UUID | None = None
    staff_id: UUID | None = Field(default=None, description="An override for one staff member")
    branch_id: UUID | None = Field(default=None, description="Empty = every branch (owner only)")
    starts_on: date
    ends_on: date | None = None


class RuleOut(RuleIn):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: UUID
    is_active: bool


class PeriodOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    branch_id: UUID
    month: date
    status: str
    closed_at: datetime | None
    paid_at: datetime | None


class CommissionLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    invoice_id: UUID
    invoice_number: str
    invoice_line_id: UUID
    source: str
    sku: str
    qty_base: int
    net_usd: Decimal
    amount: Decimal
    created_at: datetime


class StaffCommission(BaseModel):
    staff_id: UUID
    net_usd: Decimal
    commission: Decimal
    lines: int


class CommissionReport(BaseModel):
    branch_id: UUID
    month: date
    status: str
    staff: list[StaffCommission]
    total: Decimal
