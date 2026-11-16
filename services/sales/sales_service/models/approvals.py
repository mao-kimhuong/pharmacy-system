"""T2: a manual discount above the seller's cap approved on Telegram (instead of the approver's PIN at the till)."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, Numeric, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from pharmacy_shared.db import IdMixin

from .base import Base

STATUSES = ("pending", "approved", "rejected", "used")


class DiscountApproval(IdMixin, Base):
    """pending (10 min) → approved | rejected; approved → used by the seller's sale of exactly this cart (hash of
    pack, qty and manual discount per line), once, within 10 minutes of the approval."""

    __tablename__ = "discount_approvals"
    __table_args__ = (CheckConstraint(f"status IN {STATUSES}", name="ck_discount_approvals_status"),)

    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    seller_id: Mapped[UUID] = mapped_column(Uuid)
    seller_role: Mapped[str] = mapped_column(String(40))
    cart_hash: Mapped[str] = mapped_column(String(64))
    worst_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    cap_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    discount_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    total_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    needs_owner: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(10), default="pending")
    approver_id: Mapped[UUID | None] = mapped_column(Uuid)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
