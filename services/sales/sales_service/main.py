from pharmacy_shared.app_factory import create_service_app
from pharmacy_shared.consumer import EventConsumer

from .api.router import router
from .config import get_settings
from .db import db
from .models import OutboxEvent, ProcessedMessage
from .services.carts import run_scheduler as run_cart_expiry
from .services.clients import get_clients
from .services.events import ROUTING_KEYS, handle_event
from .services.orders import run_scheduler as run_order_expiry
from .services.recovery import run_recovery

settings = get_settings()

consumer = EventConsumer(
    url=settings.rabbitmq_url,
    service=settings.service_name,
    routing_keys=ROUTING_KEYS,
    db=db,
    processed_model=ProcessedMessage,
    handler=handle_event,
)


async def recovery_task(stop) -> None:  # noqa: ANN001
    await run_recovery(
        db, get_clients, stop, settings.recovery_every_seconds, settings.pending_timeout_seconds
    )


async def cart_expiry(stop) -> None:  # noqa: ANN001
    await run_cart_expiry(db, stop)


async def order_expiry(stop) -> None:  # noqa: ANN001
    await run_order_expiry(db, get_clients, stop, settings.order_expiry_every_seconds)


background = []
if settings.event_consumer_enabled:
    background.append(consumer.run)
if settings.recovery_enabled:
    background.append(recovery_task)
if settings.jobs_enabled:
    background += [cart_expiry, order_expiry]

app = create_service_app(
    settings,
    db,
    router,
    title="Pharmacy sales service",
    outbox_model=OutboxEvent,
    background=tuple(background),
)
