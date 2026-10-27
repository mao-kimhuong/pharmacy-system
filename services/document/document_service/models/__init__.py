"""SQLAlchemy models of the document service. Import every model here so
Alembic autogenerate can see it."""

from pharmacy_shared.consumer import ProcessedMessageMixin
from pharmacy_shared.db import Base
from pharmacy_shared.outbox import OutboxMixin

from .products import Product, ProductPackUnit, PurchaseOrderCopy


class OutboxEvent(OutboxMixin, Base):
    __tablename__ = "outbox"


class ProcessedMessage(ProcessedMessageMixin, Base):
    __tablename__ = "processed_messages"


__all__ = ["Base", "OutboxEvent", "ProcessedMessage", "Product", "ProductPackUnit", "PurchaseOrderCopy"]
