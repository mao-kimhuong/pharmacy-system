"""SQLAlchemy models of the sales service. Import every model here so
Alembic autogenerate can see it."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import JSON, Boolean, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pharmacy_shared.consumer import ProcessedMessageMixin
from pharmacy_shared.copies import BranchCopyMixin, PackUnitCopyMixin, ProductCopyMixin
from pharmacy_shared.numbering import DocSequenceMixin
from pharmacy_shared.outbox import OutboxMixin

from .base import Base
from .extras import (
    ORDER_STATUSES,
    CommissionLine,
    CommissionPeriod,
    CommissionRule,
    PromotionCopy,
    PromotionUse,
    SaleOrder,
    SaleOrderLine,
    SaleTemplate,
    SaleTemplateLine,
    SuspendedCart,
)  # fmt: skip
from .khqr import KhqrPayment, KhqrReconcileIssue, KhqrRefund
from .sales import (
    INVOICE_STATUSES,
    PAY_METHODS,
    ExchangeRate,
    Invoice,
    InvoiceLine,
    InvoiceLineBatch,
    InvoicePayment,
    SaleReturn,
    SaleReturnLine,
)


class OutboxEvent(OutboxMixin, Base):
    __tablename__ = "outbox"


class ProcessedMessage(ProcessedMessageMixin, Base):
    __tablename__ = "processed_messages"


class DocSequence(DocSequenceMixin, Base):
    __tablename__ = "doc_sequences"


class KnownBranch(BranchCopyMixin, Base):
    """Local copy of branches (branch.* events)."""

    __tablename__ = "known_branches"


class BranchSettingsCopy(Base):
    """Local copy of branch settings (branch.settings_updated): receipt texts and
    whether opened packs may be returned."""

    __tablename__ = "branch_settings"

    branch_id: Mapped[UUID] = mapped_column(primary_key=True)
    receipt_header: Mapped[str] = mapped_column(Text, default="")
    receipt_footer: Mapped[str] = mapped_column(Text, default="")
    allow_opened_pack_returns: Mapped[bool] = mapped_column(Boolean, default=False)
    dispensing_label_size: Mapped[str] = mapped_column(String(10), default="70x40", server_default="70x40")
    order_deposit_on_cancel: Mapped[str] = mapped_column(String(16), default="keep_as_credit",
                                                         server_default="keep_as_credit")  # fmt: skip
    max_discount_pct: Mapped[dict[str, int]] = mapped_column(
        JSON,
        default=lambda: {"cashier": 5, "pharmacist": 10, "branch_manager": 20},
        server_default='{"cashier": 5, "pharmacist": 10, "branch_manager": 20}',
    )
    receipt_lang: Mapped[str] = mapped_column(String(2), default="km", server_default="km")
    khqr: Mapped[dict | None] = mapped_column(JSON, default=None)


class KnownCustomer(Base):
    """Local copy of customers (customer.* events)."""

    __tablename__ = "known_customers"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(160))
    name_km: Mapped[str] = mapped_column(String(160), default="")
    credit_limit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    group_id: Mapped[UUID | None] = mapped_column(Uuid)  # customer-group prices (S7)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Product(ProductCopyMixin, Base):
    """Local copy of catalog medicines (medicine.* events), with sell prices."""

    __tablename__ = "products"

    pack_units: Mapped[list["ProductPackUnit"]] = relationship(back_populates="product", lazy="selectin")


class ProductPackUnit(PackUnitCopyMixin, Base):
    __tablename__ = "product_pack_units"

    product: Mapped[Product] = relationship(back_populates="pack_units", lazy="joined")


__all__ = [
    "KhqrPayment",
    "KhqrReconcileIssue",
    "KhqrRefund",
    "Base", "BranchSettingsCopy", "DocSequence", "ExchangeRate", "INVOICE_STATUSES", "Invoice", "InvoiceLine",
    "InvoiceLineBatch", "InvoicePayment", "KnownBranch", "KnownCustomer", "OutboxEvent", "PAY_METHODS",
    "ProcessedMessage", "Product", "ProductPackUnit", "SaleReturn", "SaleReturnLine", "ORDER_STATUSES",
    "CommissionLine", "CommissionPeriod", "CommissionRule", "PromotionCopy", "PromotionUse", "SaleOrder",
    "SaleOrderLine", "SaleTemplate", "SaleTemplateLine", "SuspendedCart",
]  # fmt: skip
