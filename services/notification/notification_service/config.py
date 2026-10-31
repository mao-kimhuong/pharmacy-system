from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "notification"
    api_prefix: str = "/api/notifications/v1"
    db_name: str = "pharmacy_notification"
    db_user: str = "notification_user"
    db_password: str = "change-me-notification"

    # Telegram Bot API (tests point telegram_api_base at a fake). No token: messages are kept as "skipped".
    telegram_bot_token: str = ""
    telegram_api_base: str = "https://api.telegram.org"
    # Sending: every few seconds, retry with backoff 30 s × 2^n (max 1 h), give up after max_attempts
    send_every_seconds: float = 10.0
    max_attempts: int = 8
    # Jobs, Asia/Phnom_Penh: daily summary 20:00, stock digest 07:30
    jobs_enabled: bool = True
    daily_summary_hour: int = 20
    digest_hour: int = 7
    digest_minute: int = 30
    # RabbitMQ consumer (alerts, branch and staff copies)
    event_consumer_enabled: bool = True
    # The daily figures come from the reports service (/internal/v1/daily-summary)
    reports_url: str = "http://reports:8000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
