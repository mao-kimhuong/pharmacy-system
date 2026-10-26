from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "controlled"
    api_prefix: str = "/api/controlled/v1"
    database_url: str = (
        "postgresql+asyncpg://controlled_user:change-me-controlled@localhost:5432/pharmacy_controlled"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
