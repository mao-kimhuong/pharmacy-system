"""Local copies of other services' data, kept up to date from events.

A service never reads another service's database. When it needs products or
branches it keeps its own copy, filled by an EventConsumer:

    class Product(ProductCopyMixin, Base):
        __tablename__ = "products"
        pack_units: Mapped[list["ProductPackUnit"]] = relationship(back_populates="product", lazy="selectin")

    class ProductPackUnit(PackUnitCopyMixin, Base):
        __tablename__ = "product_pack_units"
        product: Mapped[Product] = relationship(back_populates="pack_units", lazy="joined")

    class KnownBranch(BranchCopyMixin, Base):
        __tablename__ = "known_branches"

and in the event handler:

    if event_type in MEDICINE_EVENTS: await upsert_product(session, Product, ProductPackUnit, payload)
    if event_type in BRANCH_EVENTS:   await upsert_branch(session, KnownBranch, payload)

medicine.* payloads carry a `version`; an older or equal one is ignored, so
out-of-order and replayed events are harmless. branch.* payloads have no version:
the latest delivery wins (branch changes are rare and never concurrent).
Existing data can be re-sent with `python -m catalog_service.cli republish` and
`python -m branch_service.cli republish` (make resync).
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Uuid, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

MEDICINE_EVENTS = frozenset(
    {"medicine.created", "medicine.updated", "medicine.activated", "medicine.deactivated"}
)
BRANCH_EVENTS = frozenset({"branch.created", "branch.updated", "branch.activated", "branch.deactivated"})


class ProductCopyMixin:
    """A catalog medicine (table "products")."""

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
    # S7: hampers (a sellable kit of components, no stock of its own), promotion / commission scopes
    kind: Mapped[str] = mapped_column(String(10), default="medicine", server_default="medicine")
    components: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, server_default="[]")
    category_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    brand_id: Mapped[UUID | None] = mapped_column(Uuid)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @property
    def is_hamper(self) -> bool:
        return self.kind == "hamper"

    @property
    def display_name(self) -> str:
        if self.brand_name.casefold() == self.generic_name.casefold():
            return self.brand_name
        return f"{self.brand_name} ({self.generic_name})"


class PackUnitCopyMixin:
    """A catalog pack unit (table "product_pack_units")."""

    id: Mapped[UUID] = mapped_column(primary_key=True)  # the catalog pack unit id
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    qty_in_base: Mapped[int] = mapped_column(Integer)
    barcode: Mapped[str | None] = mapped_column(String(48))
    sell_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))  # USD
    is_base: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class BranchCopyMixin:
    """A branch (table "known_branches")."""

    id: Mapped[UUID] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16))
    name_km: Mapped[str] = mapped_column(String(120), default="")
    name_en: Mapped[str] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


async def upsert_product(
    session: AsyncSession, product_model: type, pack_model: type, payload: dict[str, Any]
) -> bool:
    """Store a medicine.* payload. Returns False when the stored copy is as new or newer
    (a re-send by `make resync` – payload "resync": true – also refreshes an equal version)."""
    product_id = UUID(str(payload["medicine_id"]))
    version = int(payload["version"])
    stored = (
        await session.execute(
            select(product_model.version).where(product_model.id == product_id).with_for_update()
        )
    ).scalar_one_or_none()
    if stored is not None and (stored > version or (stored == version and not payload.get("resync"))):
        return False
    values = {
        "id": product_id,
        "version": version,
        "sku": str(payload["sku"]),
        "brand_name": str(payload["brand_name"]),
        "generic_name": str(payload["generic_name"]),
        "strength": str(payload.get("strength") or ""),
        "dosage_form": str(payload.get("dosage_form") or ""),
        "name_km": str(payload.get("name_km") or ""),
        "base_unit": str(payload["base_unit"]),
        "is_rx_only": bool(payload["is_rx_only"]),
        "controlled_schedule": payload.get("controlled_schedule"),
        "is_active": bool(payload["is_active"]),
        "kind": payload.get("kind") or "medicine",
        "components": [{"medicine_id": str(c["medicine_id"]), "qty_base": int(c["qty_base"])}
                       for c in payload.get("components") or []],
        "category_id": UUID(str(payload["category"]["id"])) if (payload.get("category") or {}).get("id") else None,
        "brand_id": UUID(str(payload["brand"]["id"])) if (payload.get("brand") or {}).get("id") else None,
    }  # fmt: skip
    await session.execute(
        insert(product_model)
        .values(**values)
        .on_conflict_do_update(
            index_elements=[product_model.id], set_={k: v for k, v in values.items() if k != "id"}
        )
    )
    for pack in payload.get("pack_units") or []:
        pack_values = {
            "id": UUID(str(pack["id"])),
            "product_id": product_id,
            "name": str(pack["name"]),
            "qty_in_base": int(pack["qty_in_base"]),
            "barcode": pack.get("barcode") or None,
            "sell_price": Decimal(str(pack["sell_price"])),
            "is_base": bool(pack["is_base"]),
            "is_active": bool(pack["is_active"]),
        }
        await session.execute(
            insert(pack_model)
            .values(**pack_values)
            .on_conflict_do_update(
                index_elements=[pack_model.id], set_={k: v for k, v in pack_values.items() if k != "id"}
            )
        )
    return True


async def upsert_branch(session: AsyncSession, model: type, payload: dict[str, Any]) -> None:
    values = {
        "id": UUID(str(payload["branch_id"])),
        "code": str(payload["code"]),
        "name_km": str(payload.get("name_km") or ""),
        "name_en": str(payload["name_en"]),
        "is_active": bool(payload["is_active"]),
    }
    await session.execute(
        insert(model)
        .values(**values)
        .on_conflict_do_update(index_elements=[model.id], set_={k: v for k, v in values.items() if k != "id"})
    )
