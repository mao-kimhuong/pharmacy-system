"""The controlled-drug register and what it needs.

- RegisterEntry: append-only (a database trigger refuses UPDATE, DELETE and
  TRUNCATE). One chain per branch + medicine: each entry stores the running
  balance and sha256(prev_hash + canonical entry). Corrections are new rows
  pointing at the corrected one.
- Discrepancy: the register's balance of a batch differs from inventory's stock.
- AdjustRequest: a manual adjust / destroy (PIN + witness), sent to inventory;
  its register entry comes back with the stock.changed event.
"""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Identity,
    Index,
    Integer,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from pharmacy_shared.db import IdMixin

from .base import Base

ENTRY_TYPES = (
    "opening", "receive", "dispense", "sale_cancel", "customer_return", "supplier_return", "transfer_in",
    "transfer_out", "adjust", "destroy", "loss", "expired", "count_adjust", "correction",
)  # fmt: skip


class RegisterEntry(IdMixin, Base):
    __tablename__ = "register_entries"
    __table_args__ = (
        CheckConstraint(f"entry_type IN {ENTRY_TYPES}", name="ck_register_entry_type"),
        Index("ix_register_chain", "branch_id", "medicine_id", "seq"),
        Index("uq_register_movement", "movement_id", unique=True, postgresql_where="movement_id IS NOT NULL"),
    )

    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid)
    medicine_id: Mapped[UUID] = mapped_column(Uuid)
    batch_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    lot_no: Mapped[str] = mapped_column(String(40), default="")
    expiry_date: Mapped[date | None] = mapped_column(Date)
    entry_type: Mapped[str] = mapped_column(String(20))
    qty_base: Mapped[int] = mapped_column(Integer)  # signed
    balance_after: Mapped[int] = mapped_column(Integer)  # branch + medicine, after this entry
    ref_type: Mapped[str] = mapped_column(String(30), default="")
    ref_id: Mapped[str] = mapped_column(String(80), default="")
    movement_id: Mapped[UUID | None] = mapped_column(Uuid)
    movement_seq: Mapped[int | None] = mapped_column(BigInteger)
    prescription_id: Mapped[UUID | None] = mapped_column(Uuid)
    prescription_number: Mapped[str] = mapped_column(String(32), default="")
    patient_id: Mapped[UUID | None] = mapped_column(Uuid)
    patient_name: Mapped[str] = mapped_column(String(160), default="")
    patient_id_document: Mapped[str] = mapped_column(String(40), default="")
    actor_id: Mapped[UUID | None] = mapped_column(Uuid)
    actor_name: Mapped[str] = mapped_column(String(120), default="")
    witness_id: Mapped[UUID | None] = mapped_column(Uuid)
    witness_name: Mapped[str] = mapped_column(String(120), default="")
    reason: Mapped[str] = mapped_column(String(255), default="")
    corrects_entry_id: Mapped[UUID | None] = mapped_column(Uuid)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    prev_hash: Mapped[str] = mapped_column(String(64))
    entry_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Discrepancy(IdMixin, Base):
    __tablename__ = "discrepancies"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'resolved', 'cleared')", name="ck_discrepancies_status"),
        Index(
            "uq_discrepancy_open", "branch_id", "batch_id", unique=True, postgresql_where="status = 'open'"
        ),
    )

    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    medicine_id: Mapped[UUID] = mapped_column(Uuid)
    batch_id: Mapped[UUID] = mapped_column(Uuid)
    lot_no: Mapped[str] = mapped_column(String(40), default="")
    register_qty: Mapped[int] = mapped_column(Integer)
    stock_qty: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default="open")
    found_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[UUID | None] = mapped_column(Uuid)
    witness_id: Mapped[UUID | None] = mapped_column(Uuid)
    reason: Mapped[str] = mapped_column(String(255), default="")
    note: Mapped[str] = mapped_column(String(1000), default="")
    correction_entry_id: Mapped[UUID | None] = mapped_column(Uuid)

    @property
    def difference(self) -> int:
        return self.stock_qty - self.register_qty


class AdjustRequest(IdMixin, Base):
    __tablename__ = "adjust_requests"
    __table_args__ = (
        CheckConstraint("kind IN ('adjust_in', 'adjust_out', 'destroy')", name="ck_adjust_kind"),
    )

    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    batch_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(10))
    qty_base: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(255))
    destruction_method: Mapped[str] = mapped_column(String(120), default="")
    actor_id: Mapped[UUID] = mapped_column(Uuid)
    witness_id: Mapped[UUID] = mapped_column(Uuid)
    witness_name: Mapped[str] = mapped_column(String(120), default="")
    movement_id: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ControlledProduct(Base):
    """Copy of catalog medicines (medicine.* events); the register only uses the controlled ones."""

    __tablename__ = "products"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    sku: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(330))
    name_km: Mapped[str] = mapped_column(String(160), default="")
    strength: Mapped[str] = mapped_column(String(60), default="")
    base_unit: Mapped[str] = mapped_column(String(40))
    controlled_schedule: Mapped[str | None] = mapped_column(String(3))
    is_active: Mapped[bool] = mapped_column(default=True)


class KnownStaff(Base):
    """Names for the register (user.* events from auth)."""

    __tablename__ = "known_staff"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    is_active: Mapped[bool] = mapped_column(default=True)


class Watermark(Base):
    """The highest inventory movement seq seen in any stock.changed: a batch whose
    last movement is newer has not reached the register yet."""

    __tablename__ = "watermark"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # always 1
    last_seq: Mapped[int] = mapped_column(BigInteger, default=0)
