from pharmacy_shared.app_factory import create_service_app

from .api.router import router
from .config import get_settings
from .db import db
from .models import OutboxEvent

settings = get_settings()
app = create_service_app(
    settings, db, router, title="Pharmacy prescription service", outbox_model=OutboxEvent
)
