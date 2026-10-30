from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Usd = Annotated[Decimal, Field(ge=0, le=1_000_000, max_digits=14, decimal_places=2)]


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
