from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "reports"
    api_prefix: str = "/api/reports/v1"
    database_url: str = "postgresql+asyncpg://reports_user:change-me-reports@localhost:5432/pharmacy_reports"


@lru_cache
def get_settings() -> Settings:
    return Settings()
