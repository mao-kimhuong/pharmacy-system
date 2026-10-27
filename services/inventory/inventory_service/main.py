from pharmacy_shared.app_factory import create_service_app
from pharmacy_shared.consumer import EventConsumer

from .api.router import router
from .config import get_settings
from .db import db
from .models import OutboxEvent, ProcessedMessage
from .services.events import ROUTING_KEYS, handle_event
from .services.expiry import run_scheduler

settings = get_settings()

consumer = EventConsumer(
    url=settings.rabbitmq_url,
    service=settings.service_name,
    routing_keys=ROUTING_KEYS,
    db=db,
    processed_model=ProcessedMessage,
    handler=handle_event,
)


async def expiry_job(stop) -> None:  # noqa: ANN001
    await run_scheduler(db, stop, settings.expiry_job_hour, settings.expiry_job_minute)


background = []
if settings.event_consumer_enabled:
    background.append(consumer.run)
if settings.expiry_job_enabled:
    background.append(expiry_job)

app = create_service_app(
    settings,
    db,
    router,
    title="Pharmacy inventory service",
    outbox_model=OutboxEvent,
    background=tuple(background),
)
