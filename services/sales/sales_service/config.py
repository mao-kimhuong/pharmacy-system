from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "sales"
    api_prefix: str = "/api/sales/v1"
    database_url: str = "postgresql+asyncpg://sales_user:change-me-sales@localhost:5432/pharmacy_sales"


@lru_cache
def get_settings() -> Settings:
    return Settings()
