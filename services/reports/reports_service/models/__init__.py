"""SQLAlchemy models of the reports service. Import every model here so
Alembic autogenerate can see it."""

from pharmacy_shared.consumer import ProcessedMessageMixin
from pharmacy_shared.outbox import OutboxMixin

from .base import Base
from .read import *  # noqa: F403
from .read import __all__ as _read


class OutboxEvent(OutboxMixin, Base):
    __tablename__ = "outbox"


class ProcessedMessage(ProcessedMessageMixin, Base):
    __tablename__ = "processed_messages"


__all__ = ["Base", "OutboxEvent", "ProcessedMessage", *_read]  # noqa: PLE0604
