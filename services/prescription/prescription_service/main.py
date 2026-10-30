import logging

from pharmacy_shared.app_factory import create_service_app
from pharmacy_shared.consumer import EventConsumer

from .api.internal import router as internal_router
from .api.router import router
from .api.storage import get_storage
from .config import get_settings
from .db import db
from .models import OutboxEvent, ProcessedMessage
from .services.events import ROUTING_KEYS, handle_event
from .services.expiry import run_scheduler

settings = get_settings()
if settings.is_production:
    settings.check_storage_keys()

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


async def create_bucket() -> None:
    """The private Rx file bucket; if the store is down, uploads answer 503 until it is back."""
    if settings.storage_bucket_check:
        try:
            await get_storage().ensure_bucket()
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("could not check the Rx file bucket")


background = []
if settings.event_consumer_enabled:
    background.append(consumer.run)
if settings.expiry_job_enabled:
    background.append(expiry_job)

app = create_service_app(
    settings,
    db,
    router,
    title="Pharmacy prescription service",
    outbox_model=OutboxEvent,
    on_startup=(create_bucket,),
    background=tuple(background),
    internal_router=internal_router,
)
