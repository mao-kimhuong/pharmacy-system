from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chat_id: str = Field(pattern=r"^-?\d{3,20}$|^@[A-Za-z0-9_]{5,32}$", description="Telegram chat id or @channel")
    is_active: bool = True


class ChatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    target: str
    chat_id: str
    is_active: bool
    updated_at: datetime | None


class TestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str = Field(description='"owner" or a branch id')


class MessageOut(BaseModel):
    """Customer and supplier messages: `text` is always empty here, `summary` says what was sent."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    target: str
    kind: str
    status: str
    attempts: int
    last_error: str | None
    sent_at: datetime | None
    created_at: datetime
    text: str
    chat_role: str = "branch"
    summary: str = ""
    next_attempt_at: datetime | None = None

    @model_validator(mode="after")
    def _private(self) -> "MessageOut":
        if self.chat_role in ("customer", "supplier"):
            self.text = ""
            self.target = self.target.split(":")[0]  # no record id in the log either
        return self


Topic = Literal["receipts", "reminders", "balance", "orders", "show_medicine_names", "marketing"]


class ConsentOut(BaseModel):
    topic: Topic
    granted: bool
    source: str | None = Field(description="bot_start | bot_settings | bot_stop | staff; null: never set")
    changed_at: datetime | None


class TelegramLinkOut(BaseModel):
    id: UUID
    via: str
    label: str
    linked_at: datetime


class CustomerTelegramOut(BaseModel):
    customer_id: UUID
    linked: bool
    links: list[TelegramLinkOut]
    consents: list[ConsentOut]
    bot_configured: bool = Field(description="A bot token and username are set")


class ConsentsIn(BaseModel):
    """Staff record what the customer asked for at the counter. Marketing can only be turned ON by the
    customer (in the bot); staff may turn it off."""

    model_config = ConfigDict(extra="forbid")

    consents: dict[Topic, bool] = Field(min_length=1)


class MyTelegramOut(BaseModel):
    linked: bool
    linked_at: datetime | None
    bot_configured: bool
    can_approve: bool = Field(description="Has notifications.approve_via_telegram")


class LinkTokenOut(BaseModel):
    url: str | None = Field(description="t.me deep link; null when no bot username is set")
    expires_at: datetime


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=255)


class CampaignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    text_km: str = Field(min_length=1, max_length=900)
    text_en: str = Field(min_length=1, max_length=900)
    promotion_id: UUID | None = None


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    promotion_id: UUID | None
    queued: int = Field(description="Customers it was queued for (marketing consent, under the monthly cap)")
    over_cap: int = Field(description="Customers skipped: already 2 promotions this month")
    created_at: datetime


class InternalLinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: UUID
    ref: str = Field(min_length=1, max_length=80, description="invoice:<id> or statement:<customer>:<day>")
    via: Literal["receipt", "statement"]


class InternalLinkOut(BaseModel):
    url: str | None = Field(description="null: bot not set up, customer unknown / inactive, or already linked")


class WebhookOk(BaseModel):
    ok: bool = True


class HeartbeatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    device_id: str = Field(min_length=4, max_length=40, pattern=r"^[A-Za-z0-9_-]+$",
                           description="A random id the browser keeps (one per till)")  # fmt: skip


class SensorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    name: str = Field(min_length=1, max_length=60, examples=["Fridge A"])
    min_c: Decimal = Field(default=Decimal("2"), ge=-40, le=40, decimal_places=2)
    max_c: Decimal = Field(default=Decimal("8"), ge=-40, le=40, decimal_places=2)


class SensorUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=60)
    min_c: Decimal | None = Field(default=None, ge=-40, le=40, decimal_places=2)
    max_c: Decimal | None = Field(default=None, ge=-40, le=40, decimal_places=2)
    is_active: bool | None = None


class SensorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    branch_id: UUID
    name: str
    min_c: Decimal
    max_c: Decimal
    is_active: bool
    state: str = Field(description="ok | out (out of range) | silent")
    last_reading_at: datetime | None
    last_temp_c: Decimal | None
    token: str | None = Field(default=None, description="Only when made or renewed: shown once, put it in the device")


class ReadingIn(BaseModel):
    """What a sensor posts (Authorization: Bearer <its token>). The server's time is used."""

    model_config = ConfigDict(extra="ignore")  # devices send extra fields (battery, humidity…): ignored

    temperature_c: Decimal = Field(ge=-60, le=80, max_digits=6, decimal_places=2, examples=["5.4"])


class ReadingOut(BaseModel):
    ok: bool = True
    in_range: bool
    state: str


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    large_discount_pct: Decimal = Field(gt=0, le=100, decimal_places=2)
    large_discount_usd: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    telegram_approval_max_usd: Decimal = Field(default=Decimal("100"), ge=0, max_digits=14, decimal_places=2,
                                               description="Telegram approval buttons only up to this value")  # fmt: skip


class SettingsOut(SettingsIn):
    model_config = ConfigDict(from_attributes=True, extra="ignore")


class Queued(BaseModel):
    queued: int = Field(description="New messages queued (0 when the summary was already made)")
