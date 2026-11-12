from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

CostNote = "Only for users with finance.cost_profit"
Amount = Annotated[Decimal, Field(gt=0, max_digits=16, decimal_places=2)]


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=255)


class RateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    khr_per_usd: int = Field(ge=1000, le=10000, examples=[4100])


class RateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    branch_id: UUID
    khr_per_usd: int
    previous: int | None
    set_by: UUID | None
    set_at: datetime


# ---------------------------------------------------------------- invoices


class LineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medicine_id: UUID
    pack_unit_id: UUID
    qty: int = Field(ge=1, le=100_000, description="In the pack unit (2 strips, 1 box...)")
    batch_id: UUID | None = Field(default=None, description="Pharmacist only: sell from this batch")
    override_reason: str | None = Field(default=None, max_length=255)
    rx_item_id: UUID | None = Field(
        default=None, description="Prescription item this line dispenses (required for Rx-only medicines)"
    )
    allergy_override_reason: str | None = Field(
        default=None, max_length=255,
        description="Pharmacist with prescriptions.override_warning: sell despite an allergy warning",
    )  # fmt: skip
    acknowledge_warnings: bool = Field(
        default=False, description="Duplicate-therapy warning seen and accepted"
    )
    patient_id_document: str | None = Field(
        default=None,
        min_length=3,
        max_length=40,
        description="Controlled medicine: the patient's ID card / passport no.",
    )
    discount_pct: Decimal | None = Field(default=None, gt=0, le=100, decimal_places=2,
                                         description="Manual discount after promotions, % (capped per role)")  # fmt: skip
    discount_amount: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2,
                                            description="Manual discount after promotions, USD")  # fmt: skip


class PaymentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["cash", "card", "ABA", "KHQR", "credit", "deposit"]
    currency: Literal["USD", "KHR"] = "USD"
    amount: Amount = Field(description="In the currency; riel in whole hundreds")
    deposit_id: UUID | None = Field(
        default=None, description="method deposit: the customer's deposit (sale order)"
    )
    khqr_id: UUID | None = Field(
        default=None, description="method KHQR: the paid dynamic KHQR (POST /payments/khqr), used once"
    )


class InvoiceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    customer_id: UUID | None = None
    lines: list[LineIn] = Field(min_length=1, max_length=200)
    payments: list[PaymentIn] = Field(min_length=1, max_length=10)
    change_in: Literal["USD", "KHR", "USD_KHR"] = Field(
        default="USD_KHR", description="USD_KHR: whole dollars in USD, the cents in riel (rounded to 100)"
    )
    note: str = Field(default="", max_length=500)
    pin_token: str | None = Field(
        default=None, max_length=200,
        description="Controlled medicines: the pharmacist's PIN for controlled.dispense (auth /pin/verify)",
    )  # fmt: skip
    discount_approval_token: str | None = Field(
        default=None, max_length=200,
        description="A discount above your cap: a manager / the owner confirms (auth /pin/witness, action sales.discount)",
    )  # fmt: skip


class LineBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    batch_id: UUID
    lot_no: str
    expiry_date: date
    qty_base: int
    returned_qty_base: int
    cost_per_base: Decimal | None = Field(default=None, description=CostNote)


class LineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_no: int
    medicine_id: UUID
    pack_unit_id: UUID
    sku: str
    name: str
    name_km: str
    pack_unit: str
    qty: int
    qty_in_base: int
    qty_base: int
    unit_price: Decimal
    line_total: Decimal
    returned_qty_base: int
    batch_override_id: UUID | None
    override_reason: str | None
    batches: list[LineBatchOut] = Field(description="Batches used, earliest expiry first (FEFO)")
    cost: Decimal | None = Field(default=None, description=CostNote)
    rx_item_id: UUID | None = None
    prescription_id: UUID | None = None
    prescription_number: str | None = None
    patient_id: UUID | None = None
    patient_name_en: str | None = None
    patient_name_km: str | None = None
    dosage: str | None = None
    frequency: str | None = None
    duration_days: int | None = None
    warnings: list[dict] | None = None
    allergy_override_reason: str | None = None
    allergy_override_by: UUID | None = None
    warnings_acknowledged_by: UUID | None = None
    warnings_acknowledged_at: datetime | None = None
    is_controlled: bool = False
    patient_id_document: str | None = None
    pin_confirmed_by: UUID | None = None
    promotion_ids: list[str] = []
    promo_discount: Decimal = Decimal("0.00")
    manual_discount: Decimal = Decimal("0.00")
    manual_discount_by: UUID | None = None
    net: Decimal | None = None
    is_hamper: bool = False
    order_line_id: UUID | None = None


class InvoicePaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    method: str
    currency: str
    amount: Decimal
    amount_usd: Decimal
    deposit_id: UUID | None = None


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    number: str | None
    branch_id: UUID
    customer_id: UUID | None
    patient_id: UUID | None
    sale_order_id: UUID | None = None
    status: str
    created_by: UUID
    note: str
    subtotal: Decimal
    discount: Decimal
    total: Decimal
    paid: Decimal
    credit_amount: Decimal
    change_usd: Decimal
    khr_per_usd: int | None
    total_khr: int | None
    change_in: str
    change_given_usd: Decimal
    change_given_khr: int
    change_rounding_khr: Decimal
    returned_total: Decimal
    failure_code: str | None
    failure_reason: str | None
    cancel_reason: str | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    lines: list[LineOut]
    payments: list[InvoicePaymentOut]
    cost_total: Decimal | None = Field(default=None, description=CostNote)
    margin: Decimal | None = Field(default=None, description=CostNote)


class InvoicePage(BaseModel):
    items: list[InvoiceOut]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------- returns


class ReturnLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_line_id: UUID
    qty: int = Field(ge=1, le=100_000, description="In the line's pack unit")
    opened: bool = False


class ReturnCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lines: list[ReturnLineIn] = Field(min_length=1, max_length=200)
    refund_method: Literal["cash", "credit_note", "khqr"] = Field(
        description="khqr: back to the customer's KHQR payment of this invoice (a refund due: the refund button)")
    to: Literal["stock", "quarantine"] = "stock"
    reason: str = Field(min_length=1, max_length=255)


class ReturnLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    invoice_line_id: UUID
    batch_id: UUID
    qty_base: int
    amount: Decimal
    opened: bool


class ReturnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    number: str | None
    invoice_id: UUID
    branch_id: UUID
    refund_method: str
    refund_usd: Decimal
    to_quarantine: bool
    reason: str
    status: str
    created_at: datetime
    lines: list[ReturnLineOut]


class SoldCustomer(BaseModel):
    id: UUID
    name: str
    phone: str | None


class SoldPatient(BaseModel):
    id: UUID
    name_en: str | None
    name_km: str | None
    prescription_number: str | None


class SoldBatch(BaseModel):
    invoice_id: UUID
    number: str | None
    branch_id: UUID
    completed_at: datetime | None
    sku: str
    name: str
    batch_id: UUID
    lot_no: str
    qty_base: int = Field(description="Sold minus returned")
    customer: SoldCustomer | None
    patient: SoldPatient | None = Field(default=None, description="Rx lines, only with prescriptions.view")
