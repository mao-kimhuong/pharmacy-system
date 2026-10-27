from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pharmacy_shared.db import Base, IdMixin, TimestampMixin


class SupplierGroup(IdMixin, TimestampMixin, Base):
    """Importer, local distributor... (menu hidden by the supplier_groups switch)."""

    __tablename__ = "supplier_groups"
    __table_args__ = (Index("uq_supplier_groups_name_en", func.lower(text("name_en")), unique=True),)

    name_en: Mapped[str] = mapped_column(String(120))
    name_km: Mapped[str] = mapped_column(String(120), default="", server_default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_by: Mapped[UUID | None] = mapped_column(Uuid)

    def safe_fields(self) -> dict[str, Any]:
        return {"name_en": self.name_en, "name_km": self.name_km, "is_active": self.is_active}


class Supplier(IdMixin, TimestampMixin, Base):
    """Never deleted: deactivate. Suppliers are shared by all branches."""

    __tablename__ = "suppliers"
    __table_args__ = (CheckConstraint("payment_terms_days >= 0", name="ck_suppliers_terms"),)

    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    name_km: Mapped[str] = mapped_column(String(160), default="", server_default="")
    phone: Mapped[str] = mapped_column(String(32), default="", server_default="")
    address: Mapped[str] = mapped_column(String(255), default="", server_default="")
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    group_id: Mapped[UUID | None] = mapped_column(ForeignKey("supplier_groups.id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_by: Mapped[UUID | None] = mapped_column(Uuid)

    group: Mapped[SupplierGroup | None] = relationship(lazy="selectin")

    def safe_fields(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "name_km": self.name_km,
            "phone": self.phone,
            "address": self.address,
            "payment_terms_days": self.payment_terms_days,
            "group": self.group.name_en if self.group else None,
            "is_active": self.is_active,
        }
