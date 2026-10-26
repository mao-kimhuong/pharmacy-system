"""Transactional outbox: write the event in the same transaction as the change;
a relay publishes it to RabbitMQ later. See docs/spec.md (Architecture)."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, BigInteger, DateTime, Identity, String, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column


class OutboxMixin:
    """Use as: class OutboxEvent(OutboxMixin, Base): __tablename__ = "outbox" """

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    # Strict publish order, also for several events written in one transaction
    # (they share the same created_at).
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


def add_event(session: AsyncSession, model: type, event_type: str, payload: dict[str, Any]) -> None:
    """Queue an event in the current transaction (the caller commits).

    The relay in outbox_relay.py publishes it to RabbitMQ after the commit."""
    session.add(model(event_type=event_type, payload=payload))
