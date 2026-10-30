from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pharmacy_shared.copies import PackUnitCopyMixin, ProductCopyMixin

from .base import Base


class Product(ProductCopyMixin, Base):
    """Local copy of a catalog medicine, kept up to date from medicine.* events
    (the document service never reads the catalog database). Used for labels."""

    __tablename__ = "products"

    pack_units: Mapped[list["ProductPackUnit"]] = relationship(back_populates="product", lazy="selectin")


class ProductPackUnit(PackUnitCopyMixin, Base):
    __tablename__ = "product_pack_units"

    product: Mapped[Product] = relationship(back_populates="pack_units", lazy="joined")


class PurchaseOrderCopy(Base):
    """Local copy of a purchase order (purchase_order.* events from purchasing),
    used to print the PO PDF. `data` is the event payload; older versions are ignored."""

    __tablename__ = "purchase_orders"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    group_id: Mapped[UUID | None] = mapped_column(
        Uuid, index=True
    )  # S6: POs of several branches, one supplier
    number: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(20))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class InvoiceCopy(Base):
    """Local copy of an invoice (invoice.* events from sales), used to print the
    receipt and the A4 invoice. `data` is the event payload; older versions ignored."""

    __tablename__ = "invoices"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    number: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(20))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
