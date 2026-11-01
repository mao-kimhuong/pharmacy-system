from functools import lru_cache

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

    # KHQR (S8b): fake (tests, development) or bakong. Production refuses fake.
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

    def check_khqr(self) -> None:
        if self.is_production and self.khqr_provider != "bakong":
            raise RuntimeError("KHQR_PROVIDER must be bakong in production (the fake provider pays nothing)")


@lru_cache
def get_settings() -> Settings:
    return Settings()
