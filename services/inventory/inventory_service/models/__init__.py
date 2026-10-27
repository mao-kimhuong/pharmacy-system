"""SQLAlchemy models of the inventory service. Import every model here so
Alembic autogenerate can see it."""

from uuid import UUID

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pharmacy_shared.consumer import ProcessedMessageMixin
from pharmacy_shared.copies import BranchCopyMixin, PackUnitCopyMixin, ProductCopyMixin
from pharmacy_shared.db import Base
from pharmacy_shared.outbox import OutboxMixin

from .stock import (
    BATCH_STATUSES,
    MOVEMENT_TYPES,
    Batch,
    InitializeLock,
    Movement,
    OpeningBalance,
    OpeningLine,
    Stock,
    StockIn,
)


class OutboxEvent(OutboxMixin, Base):
    __tablename__ = "outbox"


class ProcessedMessage(ProcessedMessageMixin, Base):
    __tablename__ = "processed_messages"


class KnownBranch(BranchCopyMixin, Base):
    """Local copy of branches (branch.* events)."""

    __tablename__ = "known_branches"


class KnownSupplier(Base):
    """Local copy of suppliers (supplier.* events from purchasing)."""

    __tablename__ = "known_suppliers"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(160))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Product(ProductCopyMixin, Base):
    """Local copy of catalog medicines (medicine.* events)."""

    __tablename__ = "products"

    pack_units: Mapped[list["ProductPackUnit"]] = relationship(back_populates="product", lazy="selectin")


class ProductPackUnit(PackUnitCopyMixin, Base):
    __tablename__ = "product_pack_units"

    product: Mapped[Product] = relationship(back_populates="pack_units", lazy="joined")


__all__ = [
    "BATCH_STATUSES",
    "MOVEMENT_TYPES",
    "Base",
    "Batch",
    "InitializeLock",
    "KnownBranch",
    "KnownSupplier",
    "Movement",
    "OpeningBalance",
    "OpeningLine",
    "OutboxEvent",
    "ProcessedMessage",
    "Product",
    "ProductPackUnit",
    "Stock",
    "StockIn",
]
