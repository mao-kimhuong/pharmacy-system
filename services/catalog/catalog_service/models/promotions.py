"""Promotions (S7). The catalog owns the rules; sales keeps a copy (promotion.*
events) and applies them. Never deleted: deactivated.

Types (quantities in base units, money in USD):
- percent_off   value % off the eligible lines
- amount_off    value USD off per unit sold (the line's pack unit), at most the line
- buy_x_get_y   per medicine: of every buy_qty + get_qty base units, get_qty are free
- bundle_price  bundle_items [{medicine_id, qty_base}] together for value USD
- qty_tiers     tiers [{min_qty, percent}]: the highest tier reached by the base
                quantity of a medicine gives that % off its lines
- group_price   value USD per base unit for customers of the listed groups
Targets: medicines, categories, brands (any of them; bundle: its items).
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, Integer, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from pharmacy_shared.db import IdMixin, TimestampMixin

from .base import Base

PROMOTION_TYPES = ("percent_off", "amount_off", "buy_x_get_y", "bundle_price", "qty_tiers", "group_price")


class Promotion(IdMixin, TimestampMixin, Base):
    __tablename__ = "promotions"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (CheckConstraint(f"type IN {PROMOTION_TYPES}", name="ck_promotions_type"),)

    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    name_km: Mapped[str] = mapped_column(String(160), default="", server_default="")
    type: Mapped[str] = mapped_column(String(14))
    value: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    buy_qty: Mapped[int | None] = mapped_column(Integer)
    get_qty: Mapped[int | None] = mapped_column(Integer)
    tiers: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, server_default="[]")
    bundle_items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, server_default="[]")
    medicine_ids: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    category_ids: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    brand_ids: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    days_of_week: Mapped[list[int]] = mapped_column(JSON, default=list, server_default="[]")  # 0 = Monday
    branch_ids: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")  # empty = all
    customer_group_ids: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]"
    )  # empty = all
    max_uses_total: Mapped[int | None] = mapped_column(Integer)
    max_uses_per_customer: Mapped[int | None] = mapped_column(Integer)
    stackable: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    include_rx: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
