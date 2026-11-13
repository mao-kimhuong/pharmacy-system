from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Usd = Annotated[Decimal, Field(ge=0, le=1_000_000, max_digits=14, decimal_places=2)]
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
HHMM = Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
OpenClose = Annotated[list[HHMM], Field(min_length=2, max_length=2)]


class BranchSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    expiry_alert_days: list[int]
    receipt_header: str
    receipt_footer: str
    price_override_enabled: bool
    allow_opened_pack_returns: bool
    rx_valid_days: int
    dispensing_label_size: str
    controlled_rx_valid_days: int
    double_count_above_usd: Decimal
    owner_approval_above_usd: Decimal
    shrinkage_approval_usd: Decimal
    reorder_sales_days: int
    reorder_safety_days: int
    reorder_lead_days: int
    near_expiry_transfer_days: int
    order_deposit_on_cancel: str
    max_discount_pct: dict[str, int]
    receipt_lang: str
    khqr: dict[str, Any] | None
    refill_reminder_days: int = 3
    opening_hours: dict[str, list[str]] | None = None


class BranchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name_km: str
    name_en: str
    address: str
    phone: str
    license_no: str
    is_active: bool
    created_at: datetime


class BranchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=2, max_length=10, examples=["PP1"])
    name_km: str = Field(min_length=1, max_length=120)
    name_en: str = Field(min_length=1, max_length=120)
    address: str = Field(default="", max_length=255)
    phone: str = Field(default="", max_length=32)
    license_no: str = Field(default="", max_length=64)


class BranchUpdate(BaseModel):
    """The code cannot be changed: it prefixes invoice and PO numbers."""

    model_config = ConfigDict(extra="forbid")

    name_km: str | None = Field(default=None, min_length=1, max_length=120)
    name_en: str | None = Field(default=None, min_length=1, max_length=120)
    address: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    license_no: str | None = Field(default=None, max_length=64)


class KhqrAccount(BaseModel):
    """This branch's Bakong KHQR account (as registered with the bank)."""

    model_config = ConfigDict(extra="forbid")

    account_id: str = Field(pattern=r"^[A-Za-z0-9._-]{3,32}@[a-z0-9]{2,12}$", examples=["pharmacy@aclb"])
    merchant_name: str = Field(min_length=1, max_length=25)
    city: str = Field(default="Phnom Penh", min_length=1, max_length=15)
    merchant_id: str | None = Field(default=None, max_length=32, description="Merchant KHQR: the bank's merchant id")
    acquiring_bank: str | None = Field(default=None, max_length=32)
    currencies: list[Literal["USD", "KHR"]] = Field(default=["USD", "KHR"], min_length=1)


class BranchSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expiry_alert_days: list[int] | None = Field(default=None, examples=[[180, 90, 30]])
    receipt_header: str | None = Field(default=None, max_length=500)
    receipt_footer: str | None = Field(default=None, max_length=500)
    price_override_enabled: bool | None = None
    allow_opened_pack_returns: bool | None = None
    rx_valid_days: int | None = Field(default=None, ge=1, le=365)
    dispensing_label_size: Literal["70x40", "50x30", "100x50", "a4_sheet"] | None = None
    controlled_rx_valid_days: int | None = Field(default=None, ge=1, le=90)
    double_count_above_usd: Usd | None = Field(
        default=None, description="Stock take: count twice above this line value"
    )
    owner_approval_above_usd: Usd | None = Field(
        default=None, description="Stock take: owner approves above this total variance"
    )
    shrinkage_approval_usd: Usd | None = Field(
        default=None, description="Shrinkage above this value needs approval"
    )
    reorder_sales_days: int | None = Field(
        default=None, ge=7, le=365, description="Re-order: average sales over"
    )
    reorder_safety_days: int | None = Field(default=None, ge=0, le=90)
    reorder_lead_days: int | None = Field(
        default=None, ge=0, le=180, description="Default supplier lead time"
    )
    near_expiry_transfer_days: int | None = Field(default=None, ge=7, le=365)
    order_deposit_on_cancel: Literal["keep_as_credit", "refund", "forfeit"] | None = Field(
        default=None,
        description="A cancelled sale order's deposit: stays as credit, refunded, or kept by the shop",
    )
    max_discount_pct: dict[str, Annotated[int, Field(ge=0, le=100)]] | None = Field(
        default=None, description='Manual discount cap per role, e.g. {"cashier": 5, "pharmacist": 10}'
    )
    receipt_lang: Literal["km", "en"] | None = Field(default=None, description="Receipts and A4 invoices")
    khqr: KhqrAccount | None = Field(default=None, description="This branch's Bakong account; null: the shared one")
    refill_reminder_days: int | None = Field(default=None, ge=1, le=14,
                                             description="Telegram refill reminder this many days before")  # fmt: skip
    opening_hours: dict[Weekday, OpenClose] | None = Field(
        default=None, examples=[{"mon": ["07:00", "21:00"], "sun": ["08:00", "12:00"]}],
        description="Per weekday [open, close] (HH:MM, Phnom Penh); a day left out is closed",
    )


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=255)


class FeatureUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class FeatureOut(BaseModel):
    key: str
    label: str
    enabled: bool
    hides: list[str]
