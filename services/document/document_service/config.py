from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "document"
    api_prefix: str = "/api/documents/v1"
    db_name: str = "pharmacy_document"
    db_user: str = "document_user"
    db_password: str = "change-me-document"

    # RabbitMQ consumer (local copy of products from medicine.* events)
    event_consumer_enabled: bool = True
    # Most labels in one PDF
    max_labels: int = 1000
    # A document whose data is still on its way (event) is waited for this long
    document_wait_seconds: float = 5.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
