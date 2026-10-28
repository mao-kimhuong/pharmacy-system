"""SQLAlchemy models of the catalog service. Import every model here so
Alembic autogenerate can see it."""

from pharmacy_shared.outbox import OutboxMixin

from .base import Base
from .catalog import SCHEDULES, STORAGE, Brand, Category, Medicine, PackUnit
from .imports import ImportRow, ProductImport


class OutboxEvent(OutboxMixin, Base):
    __tablename__ = "outbox"


__all__ = [
    "Base",
    "Brand",
    "Category",
    "ImportRow",
    "Medicine",
    "OutboxEvent",
    "PackUnit",
    "ProductImport",
    "SCHEDULES",
    "STORAGE",
]
