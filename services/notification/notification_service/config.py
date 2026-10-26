from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "notification"
    api_prefix: str = "/api/notifications/v1"
    database_url: str = (
        "postgresql+asyncpg://notification_user:change-me-notification@localhost:5432/pharmacy_notification"
    )

    telegram_bot_token: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
