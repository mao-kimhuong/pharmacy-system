from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=1, max_length=32, examples=["012345678"])
    password: str = Field(min_length=1, max_length=128)


class Login2faRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mfa_token: str = Field(min_length=1, max_length=1000)
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=1, max_length=200)


class LogoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str | None = Field(default=None, max_length=200)
    all_devices: bool = False


class MenuItemOut(BaseModel):
    group: str
    key: str
    label: str


class MeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    phone: str
    role: str
    is_pharmacist: bool
    locale: str
    branch_ids: list[UUID]
    totp_enabled: bool = False
    has_pin: bool = False
    permissions: list[str] = []
    menu: list[MenuItemOut] = []
    mfa_setup_required: bool = False


class TokenResponse(BaseModel):
    """Login answer. Either tokens, or `mfa_required` with an `mfa_token` to send
    with the 6-digit code to POST /login/2fa."""

    access_token: str | None = None
    refresh_token: str | None = None
    token_type: Literal["bearer"] = "bearer"
    expires_in: int | None = None
    user: MeResponse | None = None
    mfa_required: bool = False
    mfa_token: str | None = None
    mfa_setup_required: bool = False


class TwoFactorSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str
    qr_svg: str = Field(description="data: URI of an SVG QR code, usable as <img src>")


class TwoFactorEnableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class SetPinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=128)
    pin: str = Field(min_length=4, max_length=6)
