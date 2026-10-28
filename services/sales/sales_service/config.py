from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "sales"
    api_prefix: str = "/api/sales/v1"
    db_name: str = "pharmacy_sales"
    db_user: str = "sales_user"
    db_password: str = "change-me-sales"

    # The sale saga calls these over the Docker network (/internal/v1)
    inventory_url: str = "http://inventory:8000"
    customers_url: str = "http://customers:8000"

    # RabbitMQ consumer (products, branches, branch settings, customers)
    event_consumer_enabled: bool = True
    # Recovery task: finishes compensations of sales left pending / needs_attention
    recovery_enabled: bool = True
    recovery_every_seconds: int = 60
    pending_timeout_seconds: int = 120


@lru_cache
def get_settings() -> Settings:
    return Settings()
