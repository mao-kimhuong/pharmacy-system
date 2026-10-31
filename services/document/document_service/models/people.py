"""Copies for the prescription documents (S4): staff names (user.* from auth),
patients (patient.*) and prescriptions (prescription.*) from the prescription
service. `data` is the event payload; older versions are ignored."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class StaffCopy(Base):
    """Who dispensed: the pharmacist's name on the dispensing label."""

    __tablename__ = "known_staff"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PatientCopy(Base):
    __tablename__ = "patients"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TransferCopy(Base):
    """transfer.* events from inventory: the transfer note."""

    __tablename__ = "transfers"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    from_branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    to_branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    number: Mapped[str] = mapped_column(String(32))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PrescriptionCopy(Base):
    __tablename__ = "prescriptions"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    patient_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    number: Mapped[str] = mapped_column(String(32))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SaleOrderCopy(Base):
    """sale_order.* events from sales: the quote / order PDF."""

    __tablename__ = "sale_orders"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    number: Mapped[str] = mapped_column(String(32))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
