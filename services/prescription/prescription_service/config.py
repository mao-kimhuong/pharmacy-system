from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "prescription"
    api_prefix: str = "/api/prescription/v1"
    db_name: str = "pharmacy_prescription"
    db_user: str = "prescription_user"
    db_password: str = "change-me-prescription"


@lru_cache
def get_settings() -> Settings:
    return Settings()
