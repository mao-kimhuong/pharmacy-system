from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    large_discount_pct: Decimal = Field(gt=0, le=100, decimal_places=2)
    large_discount_usd: Decimal = Field(ge=0, max_digits=14, decimal_places=2)


class SettingsOut(SettingsIn):
    model_config = ConfigDict(from_attributes=True, extra="ignore")


class Queued(BaseModel):
    queued: int = Field(description="New messages queued (0 when the summary was already made)")
