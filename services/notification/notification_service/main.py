from pharmacy_shared.app_factory import create_service_app
from pharmacy_shared.consumer import EventConsumer

from .api import customers as customers_api
from .api import staff as staff_api
from .api.internal import router as internal_router
from .api.router import router
from .config import get_settings
from .db import db
from .models import OutboxEvent, ProcessedMessage
from .services import bot
from .services.events import ROUTING_KEYS, handle_event
from .services.jobs import schedulers
from .services.staff_bot import Hooks

settings = get_settings()
settings.check_telegram()
bot.HOOKS = Hooks()

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

router.include_router(customers_api.router)
router.include_router(customers_api.public)
router.include_router(staff_api.router)
WEBHOOK = f"{settings.api_prefix}/telegram/webhook"

app = create_service_app(
    settings, db, router, title="Pharmacy notification service", outbox_model=OutboxEvent, background=background,
    internal_router=internal_router, public_paths=(WEBHOOK,), rate_limit_exempt=(WEBHOOK,),
)
