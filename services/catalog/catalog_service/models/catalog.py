from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pharmacy_shared.db import IdMixin, TimestampMixin

from .base import Base

SCHEDULES = ("I", "II", "III", "IV")
STORAGE = ("room", "cold")


class _Lookup(IdMixin, TimestampMixin):
    """Category or brand. Never deleted: deactivate. English name is unique
    (case-insensitive); it is what the Excel import matches on."""

    name_km: Mapped[str] = mapped_column(String(120), default="", server_default="")
    name_en: Mapped[str] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_by: Mapped[UUID | None] = mapped_column(Uuid)

    def safe_fields(self) -> dict[str, Any]:
        return {"name_km": self.name_km, "name_en": self.name_en, "is_active": self.is_active}


class Category(_Lookup, Base):
    __tablename__ = "categories"
    __table_args__ = (Index("uq_categories_name_en", func.lower(text("name_en")), unique=True),)


class Brand(_Lookup, Base):
    __tablename__ = "brands"
    __table_args__ = (Index("uq_brands_name_en", func.lower(text("name_en")), unique=True),)


class Medicine(IdMixin, TimestampMixin, Base):
    """A product. Never deleted: deactivate. Cost is not stored here: it lives
    on batches in the inventory service. Quantities everywhere are in base_unit."""

    __tablename__ = "medicines"
    # Read updated_at back with RETURNING after an UPDATE (async: no lazy loads).
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        CheckConstraint(
            "controlled_schedule IS NULL OR controlled_schedule IN ('I', 'II', 'III', 'IV')",
            name="ck_medicines_schedule",
        ),
        # A controlled medicine is always prescription-only.
        CheckConstraint("controlled_schedule IS NULL OR is_rx_only", name="ck_medicines_controlled_rx"),
        CheckConstraint("storage IN ('room', 'cold')", name="ck_medicines_storage"),
        CheckConstraint("reorder_level >= 0", name="ck_medicines_reorder_level"),
        Index("ix_medicines_brand_name_trgm", "brand_name", postgresql_using="gin",
              postgresql_ops={"brand_name": "gin_trgm_ops"}),
        Index("ix_medicines_generic_name_trgm", "generic_name", postgresql_using="gin",
              postgresql_ops={"generic_name": "gin_trgm_ops"}),
        Index("ix_medicines_name_km_trgm", "name_km", postgresql_using="gin",
              postgresql_ops={"name_km": "gin_trgm_ops"}),
    )  # fmt: skip

    sku: Mapped[str] = mapped_column(String(40), unique=True)
    brand_name: Mapped[str] = mapped_column(String(160))
    generic_name: Mapped[str] = mapped_column(String(160))
    strength: Mapped[str] = mapped_column(String(60), default="", server_default="")
    dosage_form: Mapped[str] = mapped_column(String(60), default="", server_default="")
    name_km: Mapped[str] = mapped_column(String(160), default="", server_default="")
    category_id: Mapped[UUID | None] = mapped_column(ForeignKey("categories.id"), index=True)
    brand_id: Mapped[UUID | None] = mapped_column(ForeignKey("brands.id"), index=True)
    manufacturer: Mapped[str] = mapped_column(String(160), default="", server_default="")
    base_unit: Mapped[str] = mapped_column(String(40))
    is_rx_only: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    controlled_schedule: Mapped[str | None] = mapped_column(String(3))
    storage: Mapped[str] = mapped_column(String(10), default="room", server_default="room")
    reorder_level: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Goes up on every change; event consumers ignore events older than their copy.
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_by: Mapped[UUID | None] = mapped_column(Uuid)

    category: Mapped[Category | None] = relationship(lazy="selectin")
    brand: Mapped[Brand | None] = relationship(lazy="selectin")
    pack_units: Mapped[list["PackUnit"]] = relationship(
        back_populates="medicine", lazy="selectin", order_by="(PackUnit.qty_in_base, PackUnit.name)"
    )

    @property
    def base_pack(self) -> "PackUnit":
        return next(p for p in self.pack_units if p.is_base)

    def safe_fields(self) -> dict[str, Any]:
        """Everything the User Log compares, pack units flattened by name so a
        price change reads as `pack_units.box.sell_price: 2.50 → 2.80`."""
        fields: dict[str, Any] = {
            "sku": self.sku,
            "brand_name": self.brand_name,
            "generic_name": self.generic_name,
            "strength": self.strength,
            "dosage_form": self.dosage_form,
            "name_km": self.name_km,
            "category": self.category.name_en if self.category else None,
            "brand": self.brand.name_en if self.brand else None,
            "manufacturer": self.manufacturer,
            "base_unit": self.base_unit,
            "is_rx_only": self.is_rx_only,
            "controlled_schedule": self.controlled_schedule,
            "storage": self.storage,
            "reorder_level": self.reorder_level,
            "is_active": self.is_active,
        }
        for p in self.pack_units:
            for key, value in p.safe_fields().items():
                fields[f"pack_units.{p.name}.{key}"] = value
        return fields


class PackUnit(IdMixin, TimestampMixin, Base):
    """How a medicine is sold: box / strip / tablet. Exactly one per medicine is
    the base unit (qty_in_base = 1). Barcodes are unique across all pack units.
    Never deleted: deactivate (the base unit cannot be deactivated)."""

    __tablename__ = "pack_units"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        CheckConstraint("qty_in_base > 0", name="ck_pack_units_qty"),
        CheckConstraint("NOT is_base OR qty_in_base = 1", name="ck_pack_units_base_qty"),
        CheckConstraint("sell_price >= 0", name="ck_pack_units_price"),
        Index("uq_pack_units_one_base", "medicine_id", unique=True, postgresql_where=text("is_base")),
        Index("uq_pack_units_name", "medicine_id", func.lower(text("name")), unique=True),
    )

    medicine_id: Mapped[UUID] = mapped_column(ForeignKey("medicines.id"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    qty_in_base: Mapped[int] = mapped_column(Integer)
    barcode: Mapped[str | None] = mapped_column(String(48), unique=True)
    sell_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))  # USD
    is_base: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    medicine: Mapped[Medicine] = relationship(back_populates="pack_units")

    def safe_fields(self) -> dict[str, Any]:
        return {
            "qty_in_base": self.qty_in_base,
            "barcode": self.barcode,
            "sell_price": str(self.sell_price),
            "is_active": self.is_active,
        }
