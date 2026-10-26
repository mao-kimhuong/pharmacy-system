from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Locale = Literal["km", "en"]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    phone: str
    role: str
    is_pharmacist: bool
    is_active: bool
    locale: str
    branch_ids: list[UUID]
    totp_enabled: bool
    created_at: datetime


class UserPage(BaseModel):
    items: list[UserOut]
    total: int
    page: int
    size: int


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=32)
    is_pharmacist: bool = False
    locale: Locale = "km"
    branch_ids: list[UUID] = []


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, min_length=1, max_length=32)
    role: str | None = Field(default=None, min_length=1, max_length=32)
    is_pharmacist: bool | None = None
    locale: Locale | None = None
    branch_ids: list[UUID] | None = None


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=255)


class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(min_length=1, max_length=128)


class PermissionOut(BaseModel):
    key: str
    group: str
    label: str


class RoleOut(BaseModel):
    key: str
    name: str
    description: str
    is_system: bool
    is_active: bool
    permissions: list[str]
    all_permissions: bool = Field(description="True for the owner role")
    active_users: int = 0


class RoleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=3, max_length=32, examples=["senior_cashier"])
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=255)
    permissions: list[str] = []


class RoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=255)
    permissions: list[str] | None = None


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    occurred_at: datetime
    service: str
    action: str
    entity_type: str
    entity_id: str | None
    actor_id: UUID | None
    actor_role: str | None
    branch_id: UUID | None
    before: dict[str, Any]
    after: dict[str, Any]
    ip: str | None


class AuditPage(BaseModel):
    items: list[AuditOut]
    total: int
    page: int
    size: int
