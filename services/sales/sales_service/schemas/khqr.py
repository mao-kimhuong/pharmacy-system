from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class KhqrCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    amount: Decimal = Field(gt=0, max_digits=16, decimal_places=2, description="USD, or KHR in whole hundreds")
    currency: Literal["USD", "KHR"] = "USD"
    cart_ref: str = Field(default="", max_length=80, description="The till's own reference for the cart")


class KhqrOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    branch_id: UUID
    amount: Decimal
    currency: str
    qr_string: str = Field(description="The EMV-KHQR string; the POS draws the QR from it")
    md5: str
    provider: Literal["fake", "bakong", "payway"]
    kind: Literal["khqr", "checkout"] = Field(description="khqr: a QR (sale method KHQR); checkout: PayWay Purchase (PAYWAY)")
    payment_option: str | None = Field(default=None, description="checkout: cards | abapay_khqr | alipay | wechat | google_pay")
    tran_id: str | None = Field(description="PayWay's transaction id (ours, sent to PayWay)")
    deeplink: str | None = Field(description="PayWay: opens the ABA app on a phone")
    status: Literal["pending", "paid", "expired", "cancelled", "used", "review", "needs_refund", "refunded"]
    expires_at: datetime
    paid_at: datetime | None
    paid_amount: Decimal | None
    paid_currency: str | None
    bank_ref: str | None
    review_reason: str | None
    refunded_amount: Decimal
    invoice_id: UUID | None


class CheckoutCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    amount: Decimal = Field(gt=0, max_digits=16, decimal_places=2, description="USD, or KHR in whole hundreds")
    currency: Literal["USD", "KHR"] = "USD"
    payment_option: Literal["cards", "abapay_khqr", "alipay", "wechat", "google_pay"] | None = Field(
        default=None, description="Empty: PayWay shows every method the merchant profile has")
    cart_ref: str = Field(default="", max_length=80)


class CheckoutForm(BaseModel):
    action: str = Field(description="PayWay's purchase URL: POST the fields there as multipart/form-data, in a new window")
    fields: dict[str, str] = Field(description="Signed by the server (hash); post them unchanged")


class CheckoutOut(BaseModel):
    payment: KhqrOut
    form: CheckoutForm | None = Field(description="None with the fake provider (development: the owner marks it paid)")


class KhqrRefundIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pin_token: str | None = Field(default=None, max_length=200, description="POST /pin/verify, action sales.khqr_refund")


class KhqrRefundOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    khqr_id: UUID
    branch_id: UUID
    source: Literal["failed_sale", "invoice_cancel", "return", "late_payment", "review"]
    source_ref: str
    amount: Decimal
    currency: str
    reason: str
    status: Literal["due", "requested", "refunded"]
    method: str | None = Field(description="payway | by_hand (Bakong: refunded at the bank) | fake")
    last_error: str | None
    refunded_at: datetime | None
    created_at: datetime
    payment: KhqrOut


class KhqrIssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_date: date
    branch_id: UUID
    khqr_id: UUID
    kind: Literal["not_paid_at_provider", "paid_not_recorded", "amount_mismatch", "refund_mismatch",
                  "paid_not_used", "refund_open"]
    ours: dict[str, Any]
    theirs: dict[str, Any]
    created_at: datetime


class CallbackOut(BaseModel):
    received: bool = True
