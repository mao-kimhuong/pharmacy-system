from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,  # fmt: skip
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from pharmacy_shared.db import IdMixin

from .base import Base

STATUSES = ("pending", "paid", "expired", "cancelled", "used", "review", "needs_refund", "refunded")


class KhqrPayment(IdMixin, Base):
    """A dynamic KHQR: pending → paid → used (by one sale), or expired / cancelled (closed at PayWay).
    review: paid, but not the amount or currency of the QR (a manager looks; refund due).
    needs_refund: paid but no completed sale keeps it (failed or cancelled sale, a late payment).
    refunded: every cent back to the customer."""

    __tablename__ = "khqr_payments"
    __table_args__ = (
        CheckConstraint(f"status IN {STATUSES}", name="ck_khqr_payments_status"),
        CheckConstraint("currency IN ('USD', 'KHR')", name="ck_khqr_payments_currency"),
        CheckConstraint("provider IN ('fake', 'bakong', 'payway')", name="ck_khqr_payments_provider"),
        CheckConstraint("kind IN ('khqr', 'checkout')", name="ck_khqr_payments_kind"),
        Index("ix_khqr_payments_pending", "status", "expires_at"),
    )

    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    invoice_id: Mapped[UUID | None] = mapped_column(Uuid)
    cart_ref: Mapped[str] = mapped_column(String(80), default="")
    provider: Mapped[str] = mapped_column(String(8), default="fake", server_default="fake")
    # khqr: a QR on the till's screen (sale method KHQR); checkout: PayWay Purchase, its hosted page in a new window
    # (cards, ABA PAY, KHQR, wallets; sale method PAYWAY)
    kind: Mapped[str] = mapped_column(String(10), default="khqr", server_default="khqr")
    payment_option: Mapped[str | None] = mapped_column(String(20))
    tran_id: Mapped[str | None] = mapped_column(String(20), unique=True)  # PayWay's transaction id (ours)
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    currency: Mapped[str] = mapped_column(String(3))
    account_id: Mapped[str] = mapped_column(String(40))
    md5: Mapped[str] = mapped_column(String(32), unique=True)
    qr_string: Mapped[str] = mapped_column(Text)
    deeplink: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(14), default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paid_amount: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    paid_currency: Mapped[str | None] = mapped_column(String(3))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bank_ref: Mapped[str | None] = mapped_column(String(80))
    review_reason: Mapped[str | None] = mapped_column(Text)
    refunded_amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=Decimal("0"), server_default="0")
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[UUID | None] = mapped_column(Uuid)
    created_by: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KhqrRefund(IdMixin, Base):
    """Money to give back on one KHQR payment, for one reason (source + ref): due → requested → refunded.
    A failed PayWay call goes back to due (last_error); one that timed out stays requested and the next try
    asks PayWay first. Once per (payment, source_ref): the same cancel or return never refunds twice."""

    __tablename__ = "khqr_refunds"
    __table_args__ = (
        UniqueConstraint("khqr_id", "source_ref", name="uq_khqr_refunds_source"),
        CheckConstraint("status IN ('due', 'requested', 'refunded')", name="ck_khqr_refunds_status"),
        CheckConstraint("source IN ('failed_sale', 'invoice_cancel', 'return', 'late_payment', 'review')",
                        name="ck_khqr_refunds_source"),  # fmt: skip
        CheckConstraint("amount > 0", name="ck_khqr_refunds_amount"),
        Index("ix_khqr_refunds_open", "branch_id", "status"),
    )

    khqr_id: Mapped[UUID] = mapped_column(ForeignKey("khqr_payments.id"), index=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid)
    source: Mapped[str] = mapped_column(String(16))
    source_ref: Mapped[str] = mapped_column(String(80))
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    currency: Mapped[str] = mapped_column(String(3))
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(10), default="due")
    method: Mapped[str | None] = mapped_column(String(10))  # payway | by_hand | fake
    last_error: Mapped[str | None] = mapped_column(String(40))
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refunded_by: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KhqrReconcileIssue(IdMixin, Base):
    """The daily check (00:40 Asia/Phnom_Penh) of yesterday's QR payments against the provider."""

    __tablename__ = "khqr_reconcile_issues"
    __table_args__ = (UniqueConstraint("run_date", "khqr_id", "kind", name="uq_khqr_reconcile_issue"),)

    run_date: Mapped[date] = mapped_column(Date, index=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    khqr_id: Mapped[UUID] = mapped_column(ForeignKey("khqr_payments.id"))
    kind: Mapped[str] = mapped_column(String(24))
    ours: Mapped[dict] = mapped_column(JSON, default=dict)
    theirs: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
