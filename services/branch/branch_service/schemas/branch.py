from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BranchSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    expiry_alert_days: list[int]
    receipt_header: str
    receipt_footer: str
    price_override_enabled: bool


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
