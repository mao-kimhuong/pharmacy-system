from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "purchasing"
    api_prefix: str = "/api/purchasing/v1"
    database_url: str = (
        "postgresql+asyncpg://purchasing_user:change-me-purchasing@localhost:5432/pharmacy_purchasing"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
