from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "reports"
    api_prefix: str = "/api/reports/v1"
    db_name: str = "pharmacy_reports"
    db_user: str = "reports_user"
    db_password: str = "change-me-reports"


@lru_cache
def get_settings() -> Settings:
    return Settings()
