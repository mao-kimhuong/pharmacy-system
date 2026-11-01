from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, Numeric, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from pharmacy_shared.db import IdMixin

from .base import Base


class KhqrPayment(IdMixin, Base):
    """A dynamic KHQR: pending → paid → used (by one sale), or expired; needs_refund
    when the sale it paid for failed (refunded by hand)."""

    __tablename__ = "khqr_payments"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'paid', 'expired', 'used', 'needs_refund')",
                        name="ck_khqr_payments_status"),  # fmt: skip
        CheckConstraint("currency IN ('USD', 'KHR')", name="ck_khqr_payments_currency"),
        Index("ix_khqr_payments_pending", "status", "expires_at"),
    )

    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    invoice_id: Mapped[UUID | None] = mapped_column(Uuid)
    cart_ref: Mapped[str] = mapped_column(String(80), default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    currency: Mapped[str] = mapped_column(String(3))
    account_id: Mapped[str] = mapped_column(String(40))
    md5: Mapped[str] = mapped_column(String(32), unique=True)
    qr_string: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(14), default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paid_amount: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bank_ref: Mapped[str | None] = mapped_column(String(80))
    created_by: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
