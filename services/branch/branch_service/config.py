from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "branch"
    api_prefix: str = "/api/branch/v1"
    db_name: str = "pharmacy_branch"
    db_user: str = "branch_user"
    db_password: str = "change-me-branch"


@lru_cache
def get_settings() -> Settings:
    return Settings()
