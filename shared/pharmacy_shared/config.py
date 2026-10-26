from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseServiceSettings(BaseSettings):
    """Settings every service has. Values come from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "service"
    environment: str = "local"
    api_prefix: str = "/api/service/v1"
    database_url: str = "postgresql+asyncpg://user:pass@localhost:5432/db"
    redis_url: str = "redis://localhost:6379/0"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"

    # Per-user rate limits (docs/spec.md, Security & reliability → Rate limits)
    rate_limit_reads_per_minute: int = 600
    rate_limit_writes_per_minute: int = 120

    # Idempotency-Key responses are kept this long
    idempotency_ttl_seconds: int = 24 * 60 * 60

    # Outbox relay
    outbox_relay_enabled: bool = True
    outbox_poll_seconds: float = 1.0
    outbox_batch_size: int = 100

    @property
    def is_production(self) -> bool:
        return self.environment == "production"
