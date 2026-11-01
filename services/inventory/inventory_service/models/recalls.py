from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pharmacy_shared.db import IdMixin

from .base import Base


class Recall(IdMixin, Base):
    """A recall of lots of one medicine: open → closed (nothing left) or lifted (owner, reason).
    branch_ids: the branches it covers (the owner's recall: every branch, empty list)."""

    __tablename__ = "recalls"
    __table_args__ = (CheckConstraint("status IN ('open', 'closed', 'lifted')", name="ck_recalls_status"),)

    number: Mapped[str] = mapped_column(String(32), unique=True)
    medicine_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    lot_nos: Mapped[list[str]] = mapped_column(JSON)
    all_branches: Mapped[bool] = mapped_column(default=False)
    branch_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    reason: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(8), default="open")
    started_by: Mapped[UUID | None] = mapped_column(Uuid)
    lift_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lines: Mapped[list["RecallLine"]] = relationship(lazy="selectin", order_by="RecallLine.created_at")


class RecallLine(IdMixin, Base):
    """One branch's stock of one recalled batch, and what was done with it."""

    __tablename__ = "recall_lines"
    __table_args__ = (
        CheckConstraint("action IN ('pending', 'returned', 'destroyed', 'none')", name="ck_recall_lines_action"),
    )

    recall_id: Mapped[UUID] = mapped_column(ForeignKey("recalls.id"), index=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("batches.id"), index=True)
    qty_at_start: Mapped[int] = mapped_column(Integer)
    previous_status: Mapped[str] = mapped_column(String(12))
    action: Mapped[str] = mapped_column(String(10), default="pending")
    action_ref: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
