from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "document"
    api_prefix: str = "/api/documents/v1"
    database_url: str = (
        "postgresql+asyncpg://document_user:change-me-document@localhost:5432/pharmacy_document"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
