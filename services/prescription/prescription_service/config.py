from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "prescription"
    api_prefix: str = "/api/prescription/v1"
    database_url: str = (
        "postgresql+asyncpg://prescription_user:change-me-prescription@localhost:5432/pharmacy_prescription"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
