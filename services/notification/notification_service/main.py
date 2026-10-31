from pharmacy_shared.app_factory import create_service_app
from pharmacy_shared.consumer import EventConsumer

from .api.router import router
from .config import get_settings
from .db import db
from .models import OutboxEvent, ProcessedMessage
from .services.events import ROUTING_KEYS, handle_event
from .services.jobs import schedulers

settings = get_settings()

consumer = EventConsumer(
    url=settings.rabbitmq_url,
    service=settings.service_name,
    routing_keys=ROUTING_KEYS,
    db=db,
    processed_model=ProcessedMessage,
    handler=handle_event,
)

background = [consumer.run] if settings.event_consumer_enabled else []
if settings.jobs_enabled:
    background += schedulers(db, settings)

app = create_service_app(
    settings, db, router, title="Pharmacy notification service", outbox_model=OutboxEvent, background=background
)
