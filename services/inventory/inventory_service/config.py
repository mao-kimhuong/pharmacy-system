from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "inventory"
    api_prefix: str = "/api/inventory/v1"
    database_url: str = (
        "postgresql+asyncpg://inventory_user:change-me-inventory@localhost:5432/pharmacy_inventory"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
