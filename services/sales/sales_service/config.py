from functools import lru_cache

from pydantic import SecretStr

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "sales"
    api_prefix: str = "/api/sales/v1"
    db_name: str = "pharmacy_sales"
    db_user: str = "sales_user"
    db_password: str = "change-me-sales"

    # The sale saga calls these over the Docker network (/internal/v1)
    inventory_url: str = "http://inventory:8000"
    customers_url: str = "http://customers:8000"
    prescription_url: str = "http://prescription:8000"

    # RabbitMQ consumer (products, branches, branch settings, customers)
    event_consumer_enabled: bool = True
    # Recovery task: finishes compensations of sales left pending / needs_attention
    recovery_enabled: bool = True
    recovery_every_seconds: int = 60
    pending_timeout_seconds: int = 120
    # S7 jobs (Asia/Phnom_Penh): suspended carts expire at 00:01; order reservations every 10 minutes
    jobs_enabled: bool = True
    order_expiry_every_seconds: int = 600

    # KHQR (S8b): fake (tests, development), bakong or payway (ABA PayWay). Production refuses fake.
    khqr_provider: str = "fake"
    khqr_expires_seconds: int = 300
    khqr_poll_seconds: float = 5.0
    khqr_mcc: str = "5912"  # drug stores and pharmacies
    # The shared Bakong account (a branch's own one comes from its settings)
    khqr_account_id: str = ""
    khqr_merchant_name: str = ""
    khqr_city: str = "Phnom Penh"
    khqr_merchant_id: str = ""
    khqr_acquiring_bank: str = ""
    bakong_api_base: str = "https://api-bakong.nbc.gov.kh"
    bakong_token: str = ""

    # ABA PayWay (KHQR_PROVIDER=payway). The API key is the HMAC-SHA512 secret ABA calls "Public Key"; the RSA
    # public key (ABA's) encrypts refunds. The private key is not needed by any API used here: never read.
    payway_base_url: str = ""
    payway_merchant_id: str = ""
    payway_api_key: SecretStr = SecretStr("")
    payway_rsa_public_key_file: str = ""
    payway_rsa_private_key_file: str = ""
    payway_callback_url: str = ""  # the public URL of POST /payments/payway/callback (empty: polling only)
    payway_qr_template: str = "template3_color"
    # Expired or cancelled QRs are still asked about this long: a late payment → needs_refund
    khqr_late_check_hours: int = 24
    khqr_late_check_every_seconds: int = 60

    def check_khqr(self) -> None:
        """At start-up. Messages name the setting, never its value."""
        if self.khqr_provider not in ("fake", "bakong", "payway"):
            raise RuntimeError("KHQR_PROVIDER must be fake, bakong or payway")
        if self.is_production and self.khqr_provider == "fake":
            raise RuntimeError("KHQR_PROVIDER must be bakong or payway in production (the fake provider pays nothing)")
        if self.khqr_provider == "payway":
            from .services.payway import check_settings

            check_settings(self)


@lru_cache
def get_settings() -> Settings:
    return Settings()
