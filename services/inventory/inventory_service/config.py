from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "inventory"
    api_prefix: str = "/api/inventory/v1"
    db_name: str = "pharmacy_inventory"
    db_user: str = "inventory_user"
    db_password: str = "change-me-inventory"


@lru_cache
def get_settings() -> Settings:
    return Settings()
