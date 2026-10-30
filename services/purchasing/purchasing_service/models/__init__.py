"""SQLAlchemy models of the purchasing service. Import every model here so
Alembic autogenerate can see it."""

from sqlalchemy.orm import Mapped, relationship

from pharmacy_shared.consumer import ProcessedMessageMixin
from pharmacy_shared.copies import BranchCopyMixin, PackUnitCopyMixin, ProductCopyMixin
from pharmacy_shared.numbering import DocSequenceMixin
from pharmacy_shared.outbox import OutboxMixin

from .base import Base
from .orders import PO_STATUSES, POLine, PurchaseOrder, Receipt, ReceiptLine
from .payments import PAYMENT_METHODS, PaymentAllocation, SupplierPayment
from .requests import POGroup, PurchaseRequest, PurchaseRequestLine
from .suppliers import Supplier, SupplierGroup


class OutboxEvent(OutboxMixin, Base):
    __tablename__ = "outbox"


class ProcessedMessage(ProcessedMessageMixin, Base):
    __tablename__ = "processed_messages"


class DocSequence(DocSequenceMixin, Base):
    __tablename__ = "doc_sequences"


class KnownBranch(BranchCopyMixin, Base):
    """Local copy of branches (branch.* events)."""

    __tablename__ = "known_branches"


class Product(ProductCopyMixin, Base):
    """Local copy of catalog medicines (medicine.* events)."""

    __tablename__ = "products"

    pack_units: Mapped[list["ProductPackUnit"]] = relationship(back_populates="product", lazy="selectin")


class ProductPackUnit(PackUnitCopyMixin, Base):
    __tablename__ = "product_pack_units"

    product: Mapped[Product] = relationship(back_populates="pack_units", lazy="joined")


__all__ = [
    "Base",
    "DocSequence",
    "KnownBranch",
    "OutboxEvent",
    "PAYMENT_METHODS",
    "PO_STATUSES",
    "POGroup",
    "POLine",
    "PaymentAllocation",
    "ProcessedMessage",
    "Product",
    "ProductPackUnit",
    "PurchaseRequest",
    "PurchaseRequestLine",
    "PurchaseOrder",
    "Receipt",
    "ReceiptLine",
    "Supplier",
    "SupplierGroup",
    "SupplierPayment",
]
