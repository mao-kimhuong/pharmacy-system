from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "notification"
    api_prefix: str = "/api/notifications/v1"
    db_name: str = "pharmacy_notification"
    db_user: str = "notification_user"
    db_password: str = "change-me-notification"

    telegram_bot_token: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
