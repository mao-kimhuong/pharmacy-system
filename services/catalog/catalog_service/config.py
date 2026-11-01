from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "catalog"
    api_prefix: str = "/api/catalog/v1"
    db_name: str = "pharmacy_catalog"
    db_user: str = "catalog_user"
    db_password: str = "change-me-catalog"

    # The promotion preview prices a sample cart in the sales service (/internal/v1/carts/preview)
    sales_url: str = "http://sales:8000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
