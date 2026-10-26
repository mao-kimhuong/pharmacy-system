"""RabbitMQ event consumer with exactly-once processing per service.

Each service that listens to events has one durable queue `<service>.events`
bound to the routing keys it cares about on the `pharmacy.events` exchange.

Delivery from RabbitMQ is at-least-once. To make the effect happen once, the
handler runs in a database transaction that also inserts the message id into
the service's `processed_messages` table; a message already in that table is
acknowledged and skipped.

A message that fails twice goes to the dead-letter queue `<service>.events.dead`
instead of blocking the queue forever. Look there when something is missing.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, String, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from .db import Database
from .outbox_relay import EXCHANGE

log = logging.getLogger(__name__)

DEAD_EXCHANGE = "pharmacy.dead"

Handler = Callable[[AsyncSession, str, dict[str, Any], UUID], Awaitable[None]]


class ProcessedMessageMixin:
    """Use as: class ProcessedMessage(ProcessedMessageMixin, Base):
    __tablename__ = "processed_messages" """

    message_id: Mapped[UUID] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


async def process_message(
    db: Database,
    processed_model: type,
    handler: Handler,
    message_id: UUID,
    event_type: str,
    payload: dict[str, Any],
) -> bool:
    """Run the handler once per message id. Returns False if it was a duplicate."""
    async with db.sessionmaker() as session, session.begin():
        seen = await session.execute(
            select(processed_model.message_id)
            .where(processed_model.message_id == message_id)
            .with_for_update()
        )
        if seen.first() is not None:
            return False
        session.add(processed_model(message_id=message_id, event_type=event_type))
        await session.flush()
        await handler(session, event_type, payload, message_id)
    return True


class EventConsumer:
    def __init__(
        self,
        *,
        url: str,
        service: str,
        routing_keys: Iterable[str],
        db: Database,
        processed_model: type,
        handler: Handler,
    ) -> None:
        self.url = url
        self.queue_name = f"{service}.events"
        self.routing_keys = list(routing_keys)
        self.db = db
        self.processed_model = processed_model
        self.handler = handler

    async def run(self, stop: asyncio.Event) -> None:
        """Consume until `stop` is set; reconnects with backoff on errors."""
        delay = 1.0
        while not stop.is_set():
            try:
                await self._consume(stop)
                delay = 1.0
            except Exception:  # noqa: BLE001
                log.warning("event consumer %s failed, retrying", self.queue_name, exc_info=True)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=delay)
                except TimeoutError:
                    pass
                delay = min(delay * 2, 30.0)

    async def _consume(self, stop: asyncio.Event) -> None:
        import aio_pika

        connection = await aio_pika.connect_robust(self.url)
        async with connection:
            channel = await connection.channel()
            await channel.set_qos(prefetch_count=20)
            exchange = await channel.declare_exchange(EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True)
            dead = await channel.declare_exchange(DEAD_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True)
            dead_queue = await channel.declare_queue(f"{self.queue_name}.dead", durable=True)
            await dead_queue.bind(dead, routing_key=self.queue_name)
            queue = await channel.declare_queue(
                self.queue_name,
                durable=True,
                arguments={
                    "x-dead-letter-exchange": DEAD_EXCHANGE,
                    "x-dead-letter-routing-key": self.queue_name,
                },
            )
            for key in self.routing_keys:
                await queue.bind(exchange, routing_key=key)

            async with queue.iterator() as messages:
                async for message in messages:
                    await self._handle(message)
                    if stop.is_set():
                        break

    async def _handle(self, message: Any) -> None:
        try:
            message_id = UUID(message.message_id)
            event_type = message.type or message.routing_key
            payload = json.loads(message.body)
            await process_message(
                self.db, self.processed_model, self.handler, message_id, event_type, payload
            )
            await message.ack()
        except Exception:  # noqa: BLE001
            log.error(
                "event %s failed (redelivered=%s)", message.message_id, message.redelivered, exc_info=True
            )
            # First failure: try again. Second failure: dead-letter queue.
            await message.reject(requeue=not message.redelivered)
