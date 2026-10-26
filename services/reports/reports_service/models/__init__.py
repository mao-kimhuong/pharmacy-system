"""SQLAlchemy models of the reports service. Import every model here so
Alembic autogenerate can see it."""

from pharmacy_shared.db import Base
from pharmacy_shared.outbox import OutboxMixin


class OutboxEvent(OutboxMixin, Base):
    __tablename__ = "outbox"


__all__ = ["Base", "OutboxEvent"]
