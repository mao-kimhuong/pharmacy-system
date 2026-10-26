from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pharmacy_shared.db import Base, IdMixin, TimestampMixin

DEFAULT_EXPIRY_ALERT_DAYS = [180, 90, 30]


class Branch(IdMixin, TimestampMixin, Base):
    """A pharmacy location. Never deleted: deactivate. The code is fixed after
    creation because it prefixes invoice and PO numbers (PP1-INV-2026-000123)."""

    __tablename__ = "branches"

    code: Mapped[str] = mapped_column(String(10), unique=True)
    name_km: Mapped[str] = mapped_column(String(120))
    name_en: Mapped[str] = mapped_column(String(120))
    address: Mapped[str] = mapped_column(String(255), default="", server_default="")
    phone: Mapped[str] = mapped_column(String(32), default="", server_default="")
    license_no: Mapped[str] = mapped_column(String(64), default="", server_default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_by: Mapped[UUID | None] = mapped_column(Uuid)

    settings: Mapped["BranchSettings"] = relationship(
        back_populates="branch", cascade="all, delete-orphan", lazy="selectin", uselist=False
    )

    def safe_fields(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name_km": self.name_km,
            "name_en": self.name_en,
            "address": self.address,
            "phone": self.phone,
            "license_no": self.license_no,
            "is_active": self.is_active,
        }


class BranchSettings(Base):
    __tablename__ = "branch_settings"

    branch_id: Mapped[UUID] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"), primary_key=True)
    # Near-expiry alerts: days before expiry, largest first (e.g. 180, 90, 30)
    expiry_alert_days: Mapped[list[int]] = mapped_column(
        JSON, default=lambda: list(DEFAULT_EXPIRY_ALERT_DAYS)
    )
    receipt_header: Mapped[str] = mapped_column(Text, default="", server_default="")
    receipt_footer: Mapped[str] = mapped_column(Text, default="", server_default="")
    # Allow this branch its own sell prices (overrides the catalog price)
    price_override_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    branch: Mapped[Branch] = relationship(back_populates="settings")

    def safe_fields(self) -> dict[str, Any]:
        return {
            "expiry_alert_days": list(self.expiry_alert_days),
            "receipt_header": self.receipt_header,
            "receipt_footer": self.receipt_footer,
            "price_override_enabled": self.price_override_enabled,
        }


class FeatureSwitch(Base):
    __tablename__ = "feature_switches"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_by: Mapped[UUID | None] = mapped_column(Uuid)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
