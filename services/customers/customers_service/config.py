from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "customers"
    api_prefix: str = "/api/customers/v1"
    database_url: str = (
        "postgresql+asyncpg://customers_user:change-me-customers@localhost:5432/pharmacy_customers"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
