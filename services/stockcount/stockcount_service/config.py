from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "stockcount"
    api_prefix: str = "/api/stockcount/v1"
    db_name: str = "pharmacy_stockcount"
    db_user: str = "stockcount_user"
    db_password: str = "change-me-stockcount"

    inventory_url: str = "http://inventory:8000"
    # RabbitMQ consumer (branches, branch settings)
    event_consumer_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
