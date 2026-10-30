from urllib.parse import quote

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


def build_database_url(host: str, port: int, name: str, user: str, password: str) -> str:
    """asyncpg URL with every part escaped, so any password works (@ : / # ? % ' $ space)."""
    url = URL.create(
        "postgresql+asyncpg", username=user, password=password, host=host, port=port, database=name
    )
    return url.render_as_string(hide_password=False)


def build_amqp_url(host: str, port: int, user: str, password: str, vhost: str = "/") -> str:
    return f"amqp://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}/{quote(vhost, safe='')}"


class BaseServiceSettings(BaseSettings):
    """Settings every service has. Values come from environment variables.

    Database and RabbitMQ connections are given as separate parts (DB_HOST,
    DB_PASSWORD, ...) and the URLs are built here with proper escaping.
    DATABASE_URL / RABBITMQ_URL, when set, override the parts (tests use them).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "service"
    environment: str = "local"
    api_prefix: str = "/api/service/v1"

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "pharmacy"
    db_user: str = "postgres"
    db_password: str = ""
    database_url: str = ""

    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "guest"
    rabbitmq_password: str = "guest"
    rabbitmq_vhost: str = "/"
    rabbitmq_url: str = ""

    redis_url: str = "redis://localhost:6379/0"

    # Calls between services (/internal/v1/...) carry this in X-Service-Token.
    # Production refuses to start when it is missing, a default or < 32 characters.
    # TODO S9: one token per calling service (see CLAUDE.md).
    service_token: str = ""
    # The auth service (PIN tokens for controlled-drug steps, pharmacy_shared.pin)
    auth_url: str = "http://auth:8000"

    # File storage, S3 API (pharmacy_shared.storage). SeaweedFS locally, cloud S3 later.
    s3_endpoint: str = "http://seaweedfs:8333"
    s3_bucket: str = "rx-files"
    s3_access_key: str = ""
    s3_secret_key: str = ""

    # Per-user rate limits (docs/spec.md, Security & reliability → Rate limits)
    rate_limit_reads_per_minute: int = 600
    rate_limit_writes_per_minute: int = 120

    # Idempotency-Key responses are kept this long
    idempotency_ttl_seconds: int = 24 * 60 * 60

    # Outbox relay
    outbox_relay_enabled: bool = True
    outbox_poll_seconds: float = 1.0
    outbox_batch_size: int = 100

    @model_validator(mode="after")
    def _build_urls(self) -> "BaseServiceSettings":
        if not self.database_url:
            self.database_url = build_database_url(
                self.db_host, self.db_port, self.db_name, self.db_user, self.db_password
            )
        if not self.rabbitmq_url:
            self.rabbitmq_url = build_amqp_url(
                self.rabbitmq_host,
                self.rabbitmq_port,
                self.rabbitmq_user,
                self.rabbitmq_password,
                self.rabbitmq_vhost,
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def check_storage_keys(self) -> None:
        """Services that store files call this in production."""
        if (
            not self.s3_access_key
            or len(self.s3_secret_key) < 20
            or self.s3_secret_key.startswith("change-me")
        ):
            raise RuntimeError(
                "S3_ACCESS_KEY / S3_SECRET_KEY must be set (secret at least 20 random characters)"
            )

    def check_service_token(self) -> None:
        token = self.service_token
        if not token or token.startswith("change-me") or len(token) < 32:
            raise RuntimeError(
                "SERVICE_TOKEN must be a random string of at least 32 characters in production "
                "(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
            )
