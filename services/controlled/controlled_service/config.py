from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "controlled"
    api_prefix: str = "/api/controlled/v1"
    db_name: str = "pharmacy_controlled"
    db_user: str = "controlled_user"
    db_password: str = "change-me-controlled"


@lru_cache
def get_settings() -> Settings:
    return Settings()
