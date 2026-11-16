"""S7 sales extras: promotions (copy + uses), suspended carts, templates, sale
orders, commission. Never deleted: statuses, deactivation, reversing lines."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pharmacy_shared.db import IdMixin, TimestampMixin

from .base import Base


class PromotionCopy(Base):
    """promotion.* events from the catalog (older versions ignored). `data` is the rule."""

    __tablename__ = "promotions"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(30))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class PromotionUse(IdMixin, Base):
    """One use per invoice: held while the sale runs, used when it completes,
    released when it fails, is cancelled or fully returned."""

    __tablename__ = "promotion_uses"
    __table_args__ = (
        UniqueConstraint("promotion_id", "invoice_id", name="uq_promotion_uses"),
        CheckConstraint("status IN ('held', 'used', 'released')", name="ck_promotion_uses_status"),
    )

    promotion_id: Mapped[UUID] = mapped_column(ForeignKey("promotions.id"), index=True)
    invoice_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    customer_id: Mapped[UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(10), default="held")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SuspendedCart(IdMixin, Base):
    __tablename__ = "suspended_carts"
    __table_args__ = (
        CheckConstraint("status IN ('suspended', 'resumed', 'expired')", name="ck_carts_status"),
    )

    number: Mapped[str] = mapped_column(String(32), unique=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    customer_id: Mapped[UUID | None] = mapped_column(Uuid)
    note: Mapped[str] = mapped_column(String(255), default="")
    lines: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON
    )  # as sent: medicine, pack, qty, Rx link, discounts
    priced: Mapped[list[dict[str, Any]]] = mapped_column(JSON)  # prices and promotions as shown when parked
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    status: Mapped[str] = mapped_column(String(10), default="suspended")
    business_date: Mapped[date] = mapped_column(Date)  # Asia/Phnom_Penh
    created_by: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resumed_by: Mapped[UUID | None] = mapped_column(Uuid)
    resumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SaleTemplate(IdMixin, TimestampMixin, Base):
    __tablename__ = "sale_templates"

    name: Mapped[str] = mapped_column(String(120))
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    customer_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)  # a customer's own basket
    note: Mapped[str] = mapped_column(String(255), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[UUID] = mapped_column(Uuid)

    lines: Mapped[list["SaleTemplateLine"]] = relationship(
        lazy="selectin", order_by="SaleTemplateLine.line_no", cascade="all, delete-orphan"
    )


class SaleTemplateLine(IdMixin, Base):
    __tablename__ = "sale_template_lines"
    __table_args__ = (CheckConstraint("qty > 0", name="ck_template_lines_qty"),)

    template_id: Mapped[UUID] = mapped_column(ForeignKey("sale_templates.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    medicine_id: Mapped[UUID] = mapped_column(Uuid)
    pack_unit_id: Mapped[UUID] = mapped_column(Uuid)
    qty: Mapped[int] = mapped_column(Integer)


ORDER_STATUSES = ("quote", "ordered", "partly_fulfilled", "fulfilled", "closed", "cancelled")


class SaleOrder(IdMixin, TimestampMixin, Base):
    __tablename__ = "sale_orders"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (CheckConstraint(f"status IN {ORDER_STATUSES}", name="ck_sale_orders_status"),)

    number: Mapped[str] = mapped_column(String(32), unique=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    customer_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    status: Mapped[str] = mapped_column(String(18), default="quote")
    note: Mapped[str] = mapped_column(String(500), default="")
    valid_until: Mapped[date | None] = mapped_column(Date)  # the quote's prices
    reserve_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reservation_id: Mapped[UUID | None] = mapped_column(Uuid)
    reservation_released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deposit_id: Mapped[UUID | None] = mapped_column(Uuid)
    deposit_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    discount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    created_by: Mapped[UUID] = mapped_column(Uuid)
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(255))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # T2: ready for pickup
    version: Mapped[int] = mapped_column(Integer, default=1)

    lines: Mapped[list["SaleOrderLine"]] = relationship(lazy="selectin", order_by="SaleOrderLine.line_no")


class SaleOrderLine(IdMixin, Base):
    __tablename__ = "sale_order_lines"
    __table_args__ = (
        CheckConstraint("qty > 0 AND qty_invoiced >= 0 AND qty_invoiced <= qty", name="ck_so_lines_qty"),
    )

    order_id: Mapped[UUID] = mapped_column(ForeignKey("sale_orders.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    medicine_id: Mapped[UUID] = mapped_column(Uuid)
    pack_unit_id: Mapped[UUID] = mapped_column(Uuid)
    sku: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(330))
    name_km: Mapped[str] = mapped_column(String(160), default="")
    pack_unit: Mapped[str] = mapped_column(String(40))
    qty: Mapped[int] = mapped_column(Integer)  # in the pack unit
    qty_in_base: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    promo_discount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    promotion_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_rx_only: Mapped[bool] = mapped_column(Boolean, default=False)
    qty_invoiced: Mapped[int] = mapped_column(Integer, default=0)

    @property
    def qty_open(self) -> int:
        return self.qty - self.qty_invoiced


class CommissionRule(IdMixin, TimestampMixin, Base):
    __tablename__ = "commission_rules"
    __table_args__ = (
        CheckConstraint("kind IN ('percent', 'per_unit')", name="ck_commission_rules_kind"),
        CheckConstraint(
            "scope IN ('all', 'medicine', 'category', 'brand')", name="ck_commission_rules_scope"
        ),
    )

    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(8))  # % of net, or USD per base unit
    value: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    scope: Mapped[str] = mapped_column(String(10))
    target_id: Mapped[UUID | None] = mapped_column(Uuid)
    staff_id: Mapped[UUID | None] = mapped_column(Uuid)  # an override for one person
    branch_id: Mapped[UUID | None] = mapped_column(Uuid)  # empty = every branch
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[UUID] = mapped_column(Uuid)


class CommissionPeriod(IdMixin, Base):
    __tablename__ = "commission_periods"
    __table_args__ = (
        UniqueConstraint("branch_id", "month", name="uq_commission_periods"),
        CheckConstraint("status IN ('open', 'closed', 'paid')", name="ck_commission_periods_status"),
    )

    branch_id: Mapped[UUID] = mapped_column(Uuid)
    month: Mapped[date] = mapped_column(Date)  # the 1st, Asia/Phnom_Penh
    status: Mapped[str] = mapped_column(String(6), default="open")
    closed_by: Mapped[UUID | None] = mapped_column(Uuid)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_by: Mapped[UUID | None] = mapped_column(Uuid)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CommissionLine(IdMixin, Base):
    """Earned (sale) or taken back (return / cancel: negative), in USD."""

    __tablename__ = "commission_lines"
    __table_args__ = (
        UniqueConstraint("invoice_line_id", "source", name="uq_commission_lines_source"),
        Index("ix_commission_lines_period_staff", "period_id", "staff_id"),
    )

    period_id: Mapped[UUID] = mapped_column(ForeignKey("commission_periods.id"))
    branch_id: Mapped[UUID] = mapped_column(Uuid)
    staff_id: Mapped[UUID] = mapped_column(Uuid)
    invoice_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    invoice_line_id: Mapped[UUID] = mapped_column(Uuid)
    invoice_number: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(60))  # "sale", "cancel", "return:<return id>"
    medicine_id: Mapped[UUID] = mapped_column(Uuid)
    sku: Mapped[str] = mapped_column(String(40))
    qty_base: Mapped[int] = mapped_column(Integer)
    net_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    rule_id: Mapped[UUID] = mapped_column(Uuid)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
