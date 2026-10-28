from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "customers"
    api_prefix: str = "/api/customers/v1"
    db_name: str = "pharmacy_customers"
    db_user: str = "customers_user"
    db_password: str = "change-me-customers"

    # RabbitMQ consumer (local copy of branches)
    event_consumer_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
