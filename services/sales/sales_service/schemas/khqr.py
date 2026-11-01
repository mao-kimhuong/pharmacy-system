from datetime import datetime
from decimal import Decimal
from typing import Literal
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
    status: Literal["pending", "paid", "expired", "used", "needs_refund"]
    expires_at: datetime
    paid_at: datetime | None
    bank_ref: str | None
    invoice_id: UUID | None
