from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pharmacy_shared.db import Base


class Product(Base):
    """Local copy of a catalog medicine, kept up to date from medicine.* events
    (the document service never reads the catalog database). Used for labels."""

    __tablename__ = "products"

    id: Mapped[UUID] = mapped_column(primary_key=True)  # the catalog medicine id
    version: Mapped[int] = mapped_column(Integer)  # catalog version; older events are ignored
    sku: Mapped[str] = mapped_column(String(40))
    brand_name: Mapped[str] = mapped_column(String(160))
    generic_name: Mapped[str] = mapped_column(String(160))
    strength: Mapped[str] = mapped_column(String(60), default="")
    dosage_form: Mapped[str] = mapped_column(String(60), default="")
    name_km: Mapped[str] = mapped_column(String(160), default="")
    base_unit: Mapped[str] = mapped_column(String(40))
    is_rx_only: Mapped[bool] = mapped_column(Boolean, default=False)
    controlled_schedule: Mapped[str | None] = mapped_column(String(3))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    pack_units: Mapped[list["ProductPackUnit"]] = relationship(back_populates="product", lazy="selectin")


class ProductPackUnit(Base):
    __tablename__ = "product_pack_units"

    id: Mapped[UUID] = mapped_column(primary_key=True)  # the catalog pack unit id
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    qty_in_base: Mapped[int] = mapped_column(Integer)
    barcode: Mapped[str | None] = mapped_column(String(48))
    sell_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))  # USD
    is_base: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    product: Mapped[Product] = relationship(back_populates="pack_units", lazy="joined")
