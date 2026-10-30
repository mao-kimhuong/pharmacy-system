from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CountStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    scope: Literal["full", "category", "location", "controlled"] = "full"
    category_id: UUID | None = None
    location: str | None = Field(default=None, max_length=12)
    note: str = Field(default="", max_length=500)


class EntryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_id: UUID
    qty: int = Field(ge=0, le=10_000_000, description="Counted, in the base unit")


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=255)


class RecountIn(ReasonIn):
    line_ids: list[UUID] = Field(min_length=1, max_length=5000)


class ApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pin_token: str | None = Field(default=None, max_length=200,
                                  description="Needed when a controlled line has a variance (stockcount.approve)")  # fmt: skip


class CounterLine(BaseModel):
    """What a counter sees: never the expected quantity nor other people's counts."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sku: str
    name: str
    name_km: str
    base_unit: str
    lot_no: str
    expiry_date: date
    location: str
    is_controlled: bool
    needs_double: bool
    status: str
    my_count: int | None = None


class ReviewLine(CounterLine):
    batch_id: UUID
    medicine_id: UUID
    snapshot_qty: int
    counted_qty: int | None
    counted_at: datetime | None
    expected_qty: int | None
    variance: int | None
    cost_per_base: Decimal | None = Field(default=None, description="Only with finance.cost_profit")
    variance_value: Decimal | None = Field(default=None, description="Only with finance.cost_profit")
    counts: list[dict] = Field(default_factory=list, description="Every count: who, how many, when, round")


class CountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    number: str
    branch_id: UUID
    scope: str
    category_id: UUID | None
    location: str
    status: str
    note: str
    started_by: UUID
    started_at: datetime
    submitted_at: datetime | None
    approved_by: UUID | None
    approved_at: datetime | None
    cancel_reason: str | None
    variance_value: Decimal | None = Field(default=None, description="Only with finance.cost_profit")
    progress: dict[str, int] = Field(default_factory=dict)


class CounterView(CountOut):
    lines: list[CounterLine]


class ReviewView(CountOut):
    lines: list[ReviewLine]
