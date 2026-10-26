from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "catalog"
    api_prefix: str = "/api/catalog/v1"
    database_url: str = "postgresql+asyncpg://catalog_user:change-me-catalog@localhost:5432/pharmacy_catalog"


@lru_cache
def get_settings() -> Settings:
    return Settings()
