"""T2 phase 4: operations alerts – till heartbeats, opening, fridge sensors."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, Index, Numeric, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from pharmacy_shared.db import IdMixin

from .base import Base


class Heartbeat(Base):
    """The newest heartbeat of one POS browser (every minute while the POS is open)."""

    __tablename__ = "heartbeats"

    branch_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[UUID | None] = mapped_column(Uuid)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BranchOps(Base):
    """Per branch: offline since (alert sent; the "back" alert clears it)."""

    __tablename__ = "branch_ops"

    branch_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    offline_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BranchDay(Base):
    """Per branch and Phnom Penh day: first and last sale (invoice.created), late-opening alert sent."""

    __tablename__ = "branch_days"

    branch_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    first_sale_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sale_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    late_alerted: Mapped[bool] = mapped_column(Boolean, default=False)


class FeatureCopy(Base):
    """feature.changed from the branch service (fridge_sensors)."""

    __tablename__ = "features"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class SensorDevice(IdMixin, Base):
    """A fridge thermometer that posts its readings with its own token (only the SHA-256 is stored).
    state: ok | out (out of range since out_since; alerted after 10 minutes) | silent (no reading for 30 minutes)."""

    __tablename__ = "sensor_devices"
    __table_args__ = (Index("uq_sensor_devices_token", "token_hash", unique=True),)

    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    name: Mapped[str] = mapped_column(String(60))
    min_c: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("2"))
    max_c: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("8"))
    token_hash: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    state: Mapped[str] = mapped_column(String(8), default="ok")
    out_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    out_alerted: Mapped[bool] = mapped_column(Boolean, default=False)
    silent_alerted: Mapped[bool] = mapped_column(Boolean, default=False)
    last_reading_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_temp_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SensorReading(IdMixin, Base):
    __tablename__ = "sensor_readings"
    __table_args__ = (Index("ix_sensor_readings_device_at", "device_id", "at"),)

    device_id: Mapped[UUID] = mapped_column(Uuid)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    temp_c: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    in_range: Mapped[bool] = mapped_column(Boolean)
