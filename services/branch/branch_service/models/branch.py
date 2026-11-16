from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pharmacy_shared.db import IdMixin, TimestampMixin

from .base import Base

DEFAULT_EXPIRY_ALERT_DAYS = [180, 90, 30]


# Manual discount caps (%) per role; the owner has none (S7).
DEFAULT_DISCOUNT_CAPS = {"cashier": 5, "pharmacist": 10, "branch_manager": 20}


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
    # Sale returns of opened packs (half a strip...) are refused unless this is on.
    allow_opened_pack_returns: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Prescriptions: valid this many days after the Rx date unless the Rx says otherwise.
    rx_valid_days: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    # Dispensing label printer: 70x40 (default), 50x30, 100x50 mm or a4_sheet.
    dispensing_label_size: Mapped[str] = mapped_column(String(10), default="70x40", server_default="70x40")
    # Controlled drugs and stock takes (S5)
    controlled_rx_valid_days: Mapped[int] = mapped_column(Integer, default=7, server_default="7")
    double_count_above_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("50.00"),
                                                            server_default="50.00")  # fmt: skip
    owner_approval_above_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("200.00"),
                                                              server_default="200.00")  # fmt: skip
    shrinkage_approval_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("50.00"),
                                                            server_default="50.00")  # fmt: skip
    # Re-ordering (S6): average sales over this many days; days of safety stock; default
    # supplier lead time; other branches' batches expiring within this many days are offered.
    reorder_sales_days: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    reorder_safety_days: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    reorder_lead_days: Mapped[int] = mapped_column(Integer, default=7, server_default="7")
    near_expiry_transfer_days: Mapped[int] = mapped_column(Integer, default=90, server_default="90")
    # Sales extras (S7): a cancelled order's deposit, manual discount caps per role (%), hamper returns
    order_deposit_on_cancel: Mapped[str] = mapped_column(String(16), default="keep_as_credit",
                                                         server_default="keep_as_credit")  # fmt: skip
    max_discount_pct: Mapped[dict[str, int]] = mapped_column(
        JSON,
        default=lambda: dict(DEFAULT_DISCOUNT_CAPS),
        server_default='{"cashier": 5, "pharmacist": 10, "branch_manager": 20}',
    )
    # S8b: language of receipts and A4 invoices; this branch's Bakong KHQR account (empty: the shared one)
    receipt_lang: Mapped[str] = mapped_column(String(2), default="km", server_default="km")
    khqr: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    # T2: Telegram refill reminders this many days before an Rx supply runs out; opening hours per weekday
    # {"mon": ["07:00", "21:00"], ...} (a day left out = closed; null = not set: no heartbeat / opening alerts)
    refill_reminder_days: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    opening_hours: Mapped[dict[str, list[str]] | None] = mapped_column(JSON, default=None)
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
            "allow_opened_pack_returns": self.allow_opened_pack_returns,
            "rx_valid_days": self.rx_valid_days,
            "dispensing_label_size": self.dispensing_label_size,
            "controlled_rx_valid_days": self.controlled_rx_valid_days,
            "double_count_above_usd": f"{self.double_count_above_usd:.2f}",
            "owner_approval_above_usd": f"{self.owner_approval_above_usd:.2f}",
            "shrinkage_approval_usd": f"{self.shrinkage_approval_usd:.2f}",
            "reorder_sales_days": self.reorder_sales_days,
            "reorder_safety_days": self.reorder_safety_days,
            "reorder_lead_days": self.reorder_lead_days,
            "near_expiry_transfer_days": self.near_expiry_transfer_days,
            "order_deposit_on_cancel": self.order_deposit_on_cancel,
            "max_discount_pct": dict(self.max_discount_pct or {}),
            "receipt_lang": self.receipt_lang,
            "khqr": dict(self.khqr) if self.khqr else None,
            "refill_reminder_days": self.refill_reminder_days,
            "opening_hours": dict(self.opening_hours) if self.opening_hours else None,
        }


class FeatureSwitch(Base):
    __tablename__ = "feature_switches"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_by: Mapped[UUID | None] = mapped_column(Uuid)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
