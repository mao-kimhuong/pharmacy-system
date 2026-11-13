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
    # The controlled-drug register PDF reads the register from the controlled service (/internal/v1)
    controlled_url: str = "http://controlled:8000"
    # The customer statement PDF reads the statement from the customers service (/internal/v1)
    customers_url: str = "http://customers:8000"
    # T2: the Telegram link (QR) on receipts, A4 invoices and statements of customers not linked yet. Asked of
    # the notification service with a short timeout; no answer = printed without the QR.
    notification_url: str = "http://notification:8000"
    telegram_link_timeout: float = 1.5


@lru_cache
def get_settings() -> Settings:
    return Settings()
