from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "sales"
    api_prefix: str = "/api/sales/v1"
    db_name: str = "pharmacy_sales"
    db_user: str = "sales_user"
    db_password: str = "change-me-sales"


@lru_cache
def get_settings() -> Settings:
    return Settings()
