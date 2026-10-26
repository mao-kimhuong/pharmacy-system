from pharmacy_shared.app_factory import create_service_app
from pharmacy_shared.consumer import EventConsumer

from .api.router import router
from .config import get_settings
from .db import db
from .models import OutboxEvent, ProcessedMessage
from .services.catalog_sync import sync_catalog
from .services.events import ROUTING_KEYS, handle_event

settings = get_settings()
settings.check_secrets()

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
    title="Pharmacy auth service",
    outbox_model=OutboxEvent,
    # Traefik calls /verify on every request from its own IP; never rate-limit it.
    rate_limit_exempt=(f"{settings.api_prefix}/verify",),
    on_startup=(sync_catalog,),
    background=(consumer.run,) if settings.event_consumer_enabled else (),
)
