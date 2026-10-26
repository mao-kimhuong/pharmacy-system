from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "branch"
    api_prefix: str = "/api/branch/v1"
    database_url: str = "postgresql+asyncpg://branch_user:change-me-branch@localhost:5432/pharmacy_branch"


@lru_cache
def get_settings() -> Settings:
    return Settings()
