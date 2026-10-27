from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "purchasing"
    api_prefix: str = "/api/purchasing/v1"
    db_name: str = "pharmacy_purchasing"
    db_user: str = "purchasing_user"
    db_password: str = "change-me-purchasing"


@lru_cache
def get_settings() -> Settings:
    return Settings()
