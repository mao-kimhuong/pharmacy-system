from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings

SOURCES = ("auth", "branch", "catalog", "inventory", "stockcount", "controlled", "sales", "customers", "purchasing")


class Settings(BaseServiceSettings):
    service_name: str = "reports"
    api_prefix: str = "/api/reports/v1"
    db_name: str = "pharmacy_reports"
    db_user: str = "reports_user"
    db_password: str = "change-me-reports"

    # RabbitMQ consumer: the read models are built from events only
    event_consumer_enabled: bool = True
    # Backfill: every service's outbox is replayed from http://<service>:8000/internal/v1/outbox
    replay_sources: tuple[str, ...] = SOURCES
    replay_url_template: str = "http://{service}:8000"
    replay_page_size: int = 500
    # Exports: rows per file (more → EXPORT_TOO_LARGE)
    export_max_rows: int = 100_000
    export_pdf_max_rows: int = 5_000
    # The PDF of a report is made by the document service (/internal/v1/render/table)
    document_url: str = "http://document:8000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
