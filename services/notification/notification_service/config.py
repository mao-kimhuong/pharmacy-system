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

    # T2 – one bot for owner, branch, staff, customer and supplier chats.
    # t.me/<username>?start=<token> links; no username: no link on receipts.
    telegram_bot_username: str = ""
    # Webhook POST /telegram/webhook checks X-Telegram-Bot-Api-Secret-Token against this; polling = getUpdates (dev)
    telegram_webhook_secret: str = ""
    telegram_mode: str = "webhook"  # webhook | polling | off
    # Key of the link tokens (HMAC; a reprinted receipt shows the same token). Empty: derived from SERVICE_TOKEN.
    telegram_link_secret: str = ""
    # Link tokens: printed (receipt, statement) and supplier ones 7 days; staff (My profile) 15 minutes
    link_token_days: int = 7
    staff_link_minutes: int = 15
    # Customer messages wait outside 07:00–21:00 (Asia/Phnom_Penh)
    quiet_from_hour: int = 21
    quiet_until_hour: int = 7
    marketing_per_month: int = 2
    refill_hour: int = 9  # refill reminders and the monthly / overdue balance reminders
    # PDFs (receipts, statements, POs) are rendered when sent; balances from customers
    document_url: str = "http://document:8000"
    customers_url: str = "http://customers:8000"
    # Bot commands per chat and minute
    commands_per_minute: int = 10
    # Phase 2 approvals: a tap is checked against auth (who, right now) and decided by the owning service
    auth_url: str = "http://auth:8000"
    inventory_url: str = "http://inventory:8000"
    stockcount_url: str = "http://stockcount:8000"
    purchasing_url: str = "http://purchasing:8000"
    sales_url: str = "http://sales:8000"
    # "Open in the app" buttons (Telegram only takes https links; otherwise the message says where to go)
    web_url: str = "http://localhost"

    def check_telegram(self) -> None:
        """Production with a bot: the webhook secret must be a real one. Names the setting, never a value."""
        if not (self.is_production and self.telegram_bot_token and self.telegram_mode == "webhook"):
            return
        if len(self.telegram_webhook_secret) < 32 or not self.telegram_webhook_secret.replace("_", "").replace(
                "-", "").isalnum():  # fmt: skip
            raise RuntimeError("TELEGRAM_WEBHOOK_SECRET must be 32+ characters of A-Z, a-z, 0-9, _ or - in production")
        if not self.telegram_bot_username:
            raise RuntimeError("TELEGRAM_BOT_USERNAME is not set (needed for the t.me links)")


@lru_cache
def get_settings() -> Settings:
    return Settings()
