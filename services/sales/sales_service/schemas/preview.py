from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .sales import LineIn, PaymentIn


class CartPreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    customer_id: UUID | None = None
    lines: list[LineIn] = Field(min_length=1, max_length=200)
    payments: list[PaymentIn] | None = Field(default=None, max_length=10,
                                             description="Optional: checks the payments settle and the credit limit")  # fmt: skip
    change_in: Literal["USD", "KHR", "USD_KHR"] = "USD_KHR"
    pin_token: str | None = Field(default=None, max_length=200, description="Never consumed by the preview")
    discount_approval_token: str | None = Field(default=None, max_length=200, description="Never consumed")


class FindingOut(BaseModel):
    code: str
    severity: Literal["hard_stop", "requirement", "warning", "info"]
    line_no: int | None
    message_en: str
    message_km: str
    details: dict[str, Any]
    resolved: bool


class PromotionApplied(BaseModel):
    id: str
    code: str
    name_en: str
    name_km: str
    discount: Decimal


class PlannedBatch(BaseModel):
    lot_no: str
    expiry_date: date
    qty_base: int
    cost_per_base: Decimal | None = Field(default=None, description="Only with finance.cost_profit (absent otherwise)")


class PreviewLine(BaseModel):
    line_no: int
    medicine_id: UUID
    pack_unit_id: UUID
    sku: str
    name: str
    pack_unit: str
    qty: int
    unit_price: Decimal
    line_total: Decimal
    promotions: list[PromotionApplied]
    promo_discount: Decimal
    manual_discount: Decimal
    net: Decimal
    batches: list[PlannedBatch]
    hard_stops: list[FindingOut]
    requirements: list[FindingOut]
    warnings: list[FindingOut]


class PreviewPayment(BaseModel):
    paid: Decimal
    credit: Decimal
    change_usd: Decimal
    change_given_usd: Decimal
    change_given_khr: int


class Conflict(BaseModel):
    line_no: int
    promotions: list[str]
    applied: list[str]
    draft_wins: bool


class CartPreviewOut(BaseModel):
    branch_id: UUID
    customer_id: UUID | None
    lines: list[PreviewLine]
    subtotal: Decimal
    discount: Decimal
    total: Decimal
    khr_per_usd: int | None
    total_khr: int | None = Field(description="Rounded to 100 riel (money.round_riel)")
    rounding_khr: Decimal | None
    hard_stops: list[FindingOut]
    requirements: list[FindingOut]
    warnings: list[FindingOut]
    payment: PreviewPayment | None = None
    conflicts: list[Conflict] | None = None
    can_post: bool


class InternalPreviewIn(BaseModel):
    """The catalog's promotion preview: a sample cart priced with a draft promotion."""

    model_config = ConfigDict(extra="forbid")

    cart: CartPreviewIn
    draft_promotion: dict[str, Any]
