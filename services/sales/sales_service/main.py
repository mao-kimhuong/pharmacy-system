from pharmacy_shared.app_factory import create_service_app
from pharmacy_shared.consumer import EventConsumer

from .api.internal import router as internal_router
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
settings.check_khqr()

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


async def khqr_poll(stop) -> None:  # noqa: ANN001
    """Pending KHQRs: paid or expired, every few seconds."""
    import asyncio
    import logging

    from .services.khqr import poll_pending

    while not stop.is_set():
        try:
            async with db.sessionmaker() as session:
                await poll_pending(session)
        except Exception:  # noqa: BLE001 – a failed round must not stop the task
            logging.getLogger(__name__).exception("khqr poll failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.khqr_poll_seconds)
        except TimeoutError:
            pass


background = []
if settings.event_consumer_enabled:
    background.append(consumer.run)
if settings.recovery_enabled:
    background.append(recovery_task)
if settings.jobs_enabled:
    background += [cart_expiry, order_expiry, khqr_poll]

app = create_service_app(
    settings,
    db,
    router,
    title="Pharmacy sales service",
    outbox_model=OutboxEvent,
    internal_router=internal_router,
    background=tuple(background),
)
