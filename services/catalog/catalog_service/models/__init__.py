"""SQLAlchemy models of the catalog service. Import every model here so
Alembic autogenerate can see it."""

from pharmacy_shared.outbox import OutboxMixin

from .base import Base
from .catalog import SCHEDULES, STORAGE, Brand, Category, HamperComponent, Medicine, PackUnit
from .imports import ImportRow, ProductImport
from .promotions import PROMOTION_TYPES, Promotion


class OutboxEvent(OutboxMixin, Base):
    __tablename__ = "outbox"


__all__ = [
    "Base",
    "Brand",
    "Category",
    "HamperComponent",
    "ImportRow",
    "Medicine",
    "OutboxEvent",
    "PackUnit",
    "ProductImport",
    "PROMOTION_TYPES",
    "Promotion",
    "SCHEDULES",
    "STORAGE",
]
