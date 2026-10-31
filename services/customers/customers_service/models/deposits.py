"""Deposits on sale orders (S7): money the customer paid before the goods. Kept
apart from the debt ledger: a deposit is used by the order's invoices, and what
is left when the order is cancelled or closed is, per branch setting, kept as
credit on the account (usable on later sales), refunded, or forfeited.
Never edited: every change is a movement (unique per reference)."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pharmacy_shared.db import IdMixin

from .base import Base


class Deposit(IdMixin, Base):
    __tablename__ = "deposits"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_deposits_amount"),
        CheckConstraint(
            "status IN ('held', 'credit', 'refunded', 'forfeited', 'used')", name="ck_deposits_status"
        ),
    )

    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid)
    ref: Mapped[str] = mapped_column(String(80), unique=True)  # the sale order
    document_no: Mapped[str] = mapped_column(String(40), default="")
    method: Mapped[str] = mapped_column(String(10))
    currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))  # USD
    status: Mapped[str] = mapped_column(String(10), default="held")
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    movements: Mapped[list["DepositMovement"]] = relationship(
        lazy="selectin", order_by="DepositMovement.created_at"
    )

    @property
    def used(self) -> Decimal:
        return sum((m.amount for m in self.movements if m.kind in ("use", "unuse")), Decimal("0.00"))

    @property
    def remaining(self) -> Decimal:
        out = sum((m.amount for m in self.movements if m.kind in ("refund", "forfeit")), Decimal("0.00"))
        return self.amount - self.used - out


class DepositMovement(IdMixin, Base):
    """use (+ taken by an invoice), unuse (− the invoice was undone), refund, forfeit."""

    __tablename__ = "deposit_movements"
    __table_args__ = (
        UniqueConstraint("deposit_id", "kind", "ref", name="uq_deposit_movement"),
        CheckConstraint("kind IN ('use', 'unuse', 'refund', 'forfeit')", name="ck_deposit_movements_kind"),
    )

    deposit_id: Mapped[UUID] = mapped_column(ForeignKey("deposits.id"), index=True)
    kind: Mapped[str] = mapped_column(String(8))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))  # signed: unuse is negative
    ref: Mapped[str] = mapped_column(String(80))  # invoice id / reason ref
    reason: Mapped[str] = mapped_column(String(255), default="")
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
