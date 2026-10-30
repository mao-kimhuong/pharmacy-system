"""Stock takes. A count is counting → review → approved, or cancelled (reason).

- Lines are the batches in the snapshot inventory took at the start (scope:
  full, category, shelf location or controlled medicines).
- Entries are what people counted (blind: counters never see expected figures).
- A line is "agreed" when one count is enough, or, for controlled lines and
  lines worth more than the branch limit, when two different people counted
  the same number.
"""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pharmacy_shared.db import IdMixin

from .base import Base

SCOPES = ("full", "category", "location", "controlled")
COUNT_STATUSES = ("counting", "review", "approved", "cancelled")
LINE_STATUSES = ("pending", "needs_second", "recount", "agreed")


class Count(IdMixin, Base):
    __tablename__ = "counts"
    __table_args__ = (
        CheckConstraint(f"status IN {COUNT_STATUSES}", name="ck_counts_status"),
        CheckConstraint(f"scope IN {SCOPES}", name="ck_counts_scope"),
    )

    number: Mapped[str] = mapped_column(String(32), unique=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    scope: Mapped[str] = mapped_column(String(12))
    category_id: Mapped[UUID | None] = mapped_column(Uuid)
    location: Mapped[str] = mapped_column(String(12), default="")
    status: Mapped[str] = mapped_column(String(12), default="counting")
    as_of_seq: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String(500), default="")
    started_by: Mapped[UUID] = mapped_column(Uuid)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    submitted_by: Mapped[UUID | None] = mapped_column(Uuid)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[UUID | None] = mapped_column(Uuid)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(255))
    variance_value: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0")
    )  # sum |variance × cost|
    version: Mapped[int] = mapped_column(Integer, default=1)

    lines: Mapped[list["CountLine"]] = relationship(
        back_populates="count",
        lazy="selectin",
        order_by="(CountLine.location, CountLine.sku, CountLine.expiry_date)",
    )


class CountLine(IdMixin, Base):
    __tablename__ = "count_lines"
    __table_args__ = (CheckConstraint(f"status IN {LINE_STATUSES}", name="ck_count_lines_status"),)

    count_id: Mapped[UUID] = mapped_column(ForeignKey("counts.id"), index=True)
    batch_id: Mapped[UUID] = mapped_column(Uuid)
    medicine_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    sku: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(330))
    name_km: Mapped[str] = mapped_column(String(160), default="")
    base_unit: Mapped[str] = mapped_column(String(40))
    lot_no: Mapped[str] = mapped_column(String(40))
    expiry_date: Mapped[date] = mapped_column(Date)
    location: Mapped[str] = mapped_column(String(12), default="")
    barcodes: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_controlled: Mapped[bool] = mapped_column(default=False)
    cost_per_base: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    snapshot_qty: Mapped[int] = mapped_column(Integer)
    needs_double: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(12), default="pending")
    round: Mapped[int] = mapped_column(Integer, default=1)  # a recount starts a new round; old counts stay
    counted_qty: Mapped[int | None] = mapped_column(Integer)  # the agreed count
    counted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expected_qty: Mapped[int | None] = mapped_column(Integer)  # snapshot + sales etc. until counted
    variance: Mapped[int | None] = mapped_column(Integer)  # counted − expected

    count: Mapped[Count] = relationship(back_populates="lines")
    entries: Mapped[list["CountEntry"]] = relationship(lazy="selectin", order_by="CountEntry.counted_at")

    @property
    def variance_value(self) -> Decimal | None:
        if self.variance is None:
            return None
        return (self.cost_per_base * self.variance).quantize(Decimal("0.01"))


class CountEntry(IdMixin, Base):
    __tablename__ = "count_entries"
    # counted_at is the database's clock (the same server as inventory's movements), read back on insert
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (CheckConstraint("qty >= 0", name="ck_count_entries_qty"),)

    line_id: Mapped[UUID] = mapped_column(ForeignKey("count_lines.id"), index=True)
    user_id: Mapped[UUID] = mapped_column(Uuid)
    round: Mapped[int] = mapped_column(Integer, default=1)
    qty: Mapped[int] = mapped_column(Integer)
    counted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
