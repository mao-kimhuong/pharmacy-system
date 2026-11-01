from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=1, max_length=32, examples=["012345678"])
    password: str = Field(min_length=1, max_length=128)


class Login2faRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mfa_token: str = Field(min_length=1, max_length=1000)
    code: str | None = Field(default=None, min_length=6, max_length=6, pattern=r"^\d{6}$")
    backup_code: str | None = Field(default=None, min_length=10, max_length=12,
                                    description="Instead of the 6-digit code (lost phone): one of your backup codes")

    @model_validator(mode="after")
    def _one(self) -> "Login2faRequest":
        if (self.code is None) == (self.backup_code is None):
            raise ValueError("Send either code or backup_code")
        return self


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
    backup_codes_left: int | None = Field(default=None, description="Unused 2FA backup codes (with 2FA on)")
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
    backup_codes: list[str] | None = Field(default=None, description="Shown once, when 2FA is turned on")


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


class PinVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pin: str = Field(min_length=4, max_length=6)
    action: str = Field(min_length=3, max_length=60, examples=["controlled.dispense"])


class PinWitnessRequest(PinVerifyRequest):
    witness_user_id: UUID


class PinTokenOut(BaseModel):
    pin_token: str
    expires_at: datetime
    user_id: UUID
    name: str


class WitnessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    role: str
    is_pharmacist: bool


class PinConsumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=10, max_length=200)
    action: str = Field(min_length=3, max_length=60)
    kind: Literal["actor", "witness"]


class BackupCodesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=200)


class BackupCodesOut(BaseModel):
    codes: list[str] = Field(description="Shown only now: store them safely; the old set no longer works")


class SessionOut(BaseModel):
    id: UUID
    started_at: datetime
    last_used_at: datetime
    expires_at: datetime
    ip: str | None
    user_agent: str | None
    current: bool
