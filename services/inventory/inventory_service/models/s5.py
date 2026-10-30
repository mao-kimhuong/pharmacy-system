"""S5: shelf locations, shrinkage, the branch settings inventory needs."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pharmacy_shared.db import IdMixin

from .base import Base
from .stock import Batch

SHRINKAGE_REASONS = ("expired", "damaged", "broken", "lost_theft", "recalled")
SHRINKAGE_STATUSES = ("pending_approval", "posted", "rejected")


class ShelfLocation(Base):
    """Where a medicine sits at a branch (a short code like "A3"); stock takes can be
    scoped by it. Managers set it; an empty code means "no location"."""

    __tablename__ = "shelf_locations"

    branch_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    medicine_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    code: Mapped[str] = mapped_column(String(12), index=True)
    updated_by: Mapped[UUID | None] = mapped_column(Uuid)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BranchSettingsCopy(Base):
    """From branch.settings_updated: the shrinkage value above which a manager approves."""

    __tablename__ = "branch_settings"

    branch_id: Mapped[UUID] = mapped_column(primary_key=True)
    shrinkage_approval_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("50.00"))


class Shrinkage(IdMixin, Base):
    """Stock written off (damaged, lost, expired...). Never deleted: pending → posted
    (a "shrinkage" movement) or rejected (reason)."""

    __tablename__ = "shrinkages"
    __table_args__ = (
        CheckConstraint("qty_base > 0", name="ck_shrinkages_qty"),
        CheckConstraint(f"reason IN {SHRINKAGE_REASONS}", name="ck_shrinkages_reason"),
        CheckConstraint(f"status IN {SHRINKAGE_STATUSES}", name="ck_shrinkages_status"),
    )

    number: Mapped[str] = mapped_column(String(32), unique=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("batches.id"), index=True)
    medicine_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    qty_base: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(12))
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    destruction_method: Mapped[str] = mapped_column(String(120), default="", server_default="")
    value: Mapped[Decimal] = mapped_column(Numeric(14, 2))  # qty × cost per base, USD
    status: Mapped[str] = mapped_column(String(16))
    is_controlled: Mapped[bool] = mapped_column(default=False)
    witness_id: Mapped[UUID | None] = mapped_column(Uuid)
    witness_name: Mapped[str] = mapped_column(String(120), default="", server_default="")
    photo_key: Mapped[str | None] = mapped_column(String(80))
    photo_type: Mapped[str | None] = mapped_column(String(40))
    movement_id: Mapped[UUID | None] = mapped_column(Uuid)
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
    decided_by: Mapped[UUID | None] = mapped_column(Uuid)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reject_reason: Mapped[str | None] = mapped_column(String(255))
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    batch: Mapped[Batch] = relationship(lazy="joined", innerjoin=True)
