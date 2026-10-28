"""SQLAlchemy models of the notification service. Import every model here so
Alembic autogenerate can see it."""

from pharmacy_shared.outbox import OutboxMixin

from .base import Base


class OutboxEvent(OutboxMixin, Base):
    __tablename__ = "outbox"


__all__ = ["Base", "OutboxEvent"]
