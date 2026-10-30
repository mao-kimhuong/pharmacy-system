from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "controlled"
    api_prefix: str = "/api/controlled/v1"
    db_name: str = "pharmacy_controlled"
    db_user: str = "controlled_user"
    db_password: str = "change-me-controlled"

    inventory_url: str = "http://inventory:8000"
    # RabbitMQ consumer (branches, medicines, staff, stock.changed)
    event_consumer_enabled: bool = True
    # Daily register check: chains + register vs stock (00:20 Asia/Phnom_Penh, and at start-up)
    check_job_enabled: bool = True
    check_job_hour: int = 0
    check_job_minute: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()
