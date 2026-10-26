from pharmacy_shared.app_factory import create_service_app

from .api.router import router
from .config import get_settings
from .db import db
from .models import OutboxEvent
from .services.branches import sync_features

settings = get_settings()


async def _sync_features() -> None:
    async with db.sessionmaker() as session:
        await sync_features(session)


app = create_service_app(
    settings,
    db,
    router,
    title="Pharmacy branch service",
    outbox_model=OutboxEvent,
    on_startup=(_sync_features,),
)
