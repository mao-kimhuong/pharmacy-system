from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "stockcount"
    api_prefix: str = "/api/stockcount/v1"
    database_url: str = (
        "postgresql+asyncpg://stockcount_user:change-me-stockcount@localhost:5432/pharmacy_stockcount"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
