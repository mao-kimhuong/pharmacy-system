from pharmacy_shared.app_factory import create_service_app
from pharmacy_shared.consumer import EventConsumer

from .api.internal import router as internal_router
from .api.router import router
from .config import get_settings
from .db import db
from .models import OutboxEvent, ProcessedMessage
from .services.events import ROUTING_KEYS, handle_event

settings = get_settings()

consumer = EventConsumer(
    url=settings.rabbitmq_url,
    service=settings.service_name,
    routing_keys=ROUTING_KEYS,
    db=db,
    processed_model=ProcessedMessage,
    handler=handle_event,
)

app = create_service_app(
    settings,
    db,
    router,
    title="Pharmacy reports service",
    outbox_model=OutboxEvent,
    internal_router=internal_router,
    background=(consumer.run,) if settings.event_consumer_enabled else (),
)
