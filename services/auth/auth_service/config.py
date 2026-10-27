from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "auth"
    api_prefix: str = "/api/auth/v1"
    db_name: str = "pharmacy_auth"
    db_user: str = "auth_user"
    db_password: str = "change-me-auth"

    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_minutes: int = 15
    jwt_refresh_days: int = 7

    # docs/spec.md → Security & reliability → Logins and sessions / Rate limits
    lockout_threshold: int = 10
    lockout_minutes: int = 15
    login_attempts_per_minute: int = 5

    # Two-factor login: these roles must use an authenticator app
    require_2fa_roles: str = "owner,branch_manager"
    totp_issuer: str = "Pharmacy"
    # Key for encrypting TOTP secrets (Fernet, urlsafe base64, 32 bytes).
    # Empty = derived from JWT_SECRET; set it separately in production.
    totp_encryption_key: str = ""
    mfa_token_minutes: int = 5

    # RabbitMQ consumer (User Log entries from other services, branch list)
    event_consumer_enabled: bool = True

    @property
    def roles_requiring_2fa(self) -> frozenset[str]:
        return frozenset(r.strip() for r in self.require_2fa_roles.split(",") if r.strip())

    def check_secrets(self) -> None:
        """Refuse to start in production with a weak or default JWT secret."""
        if self.is_production and (self.jwt_secret.startswith("change-me") or len(self.jwt_secret) < 32):
            raise RuntimeError("JWT_SECRET must be a random string of at least 32 characters in production")


@lru_cache
def get_settings() -> Settings:
    return Settings()
