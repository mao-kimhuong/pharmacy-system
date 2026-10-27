from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "inventory"
    api_prefix: str = "/api/inventory/v1"
    db_name: str = "pharmacy_inventory"
    db_user: str = "inventory_user"
    db_password: str = "change-me-inventory"

    # RabbitMQ consumer (branches, medicines, suppliers, goods.received)
    event_consumer_enabled: bool = True
    # Stock-in / opening stock: an expiry closer than this many days is flagged
    short_expiry_days: int = 180
    # Nightly expiry job (00:05 Asia/Phnom_Penh; also once at start-up)
    expiry_job_enabled: bool = True
    expiry_job_hour: int = 0
    expiry_job_minute: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
