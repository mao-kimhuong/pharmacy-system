"""Outbox relay: publishes rows from a service's `outbox` table to RabbitMQ.

Delivery is at-least-once: if the service stops after publishing but before the
commit, the event is published again on the next run. Every message carries the
outbox row id as `message_id`, so consumers must ignore ids they have seen.

Events go to the durable topic exchange `pharmacy.events` with the event type as
routing key (e.g. `user.logged_in`, `invoice.created`).
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

log = logging.getLogger(__name__)

EXCHANGE = "pharmacy.events"


class Publisher(Protocol):
    async def publish(self, event_type: str, payload: dict[str, Any], message_id: UUID) -> None: ...


class RabbitPublisher:
    """Publishes with publisher confirms; reconnects automatically."""

    def __init__(self, url: str, service: str) -> None:
        self.url = url
        self.service = service
        self._connection: Any = None
        self._exchange: Any = None

    async def _ensure(self) -> None:
        if self._exchange is not None:
            return
        import aio_pika

        self._connection = await aio_pika.connect_robust(self.url)
        channel = await self._connection.channel(publisher_confirms=True)
        self._exchange = await channel.declare_exchange(EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True)

    async def publish(self, event_type: str, payload: dict[str, Any], message_id: UUID) -> None:
        import aio_pika

        await self._ensure()
        message = aio_pika.Message(
            body=json.dumps(payload, default=str).encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=str(message_id),
            type=event_type,
            app_id=self.service,
        )
        await self._exchange.publish(message, routing_key=event_type)

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
        self._connection = None
        self._exchange = None


async def relay_once(
    sessionmaker: async_sessionmaker[AsyncSession],
    model: type,
    publisher: Publisher,
    batch_size: int = 100,
) -> int:
    """Publish up to `batch_size` unpublished events, oldest first. Returns how many."""
    async with sessionmaker() as session, session.begin():
        rows = (
            (
                await session.execute(
                    select(model)
                    .where(model.published_at.is_(None))
                    .order_by(model.seq)
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            await publisher.publish(row.event_type, row.payload, row.id)
            row.published_at = datetime.now(UTC)
        return len(rows)


async def run_relay(
    sessionmaker_factory: Any,
    model: type,
    publisher: Publisher,
    *,
    poll_seconds: float,
    batch_size: int,
    stop: asyncio.Event,
) -> None:
    """Loop until `stop` is set. Errors are logged and retried with backoff."""
    delay = poll_seconds
    while not stop.is_set():
        try:
            sent = await relay_once(sessionmaker_factory(), model, publisher, batch_size)
            delay = poll_seconds
            if sent == batch_size:
                continue  # more waiting, go again right away
        except Exception:  # noqa: BLE001
            log.warning("outbox relay failed, retrying", exc_info=True)
            delay = min(delay * 2, 30.0)
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except TimeoutError:
            pass
