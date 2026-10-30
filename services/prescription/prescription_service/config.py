from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "prescription"
    api_prefix: str = "/api/prescription/v1"
    db_name: str = "pharmacy_prescription"
    db_user: str = "prescription_user"
    db_password: str = "change-me-prescription"

    # RabbitMQ consumer (branches + settings, medicines, customers, invoices)
    event_consumer_enabled: bool = True
    # Daily job: open prescriptions past valid_until → expired (00:10 Asia/Phnom_Penh, and at start-up)
    expiry_job_enabled: bool = True
    expiry_job_hour: int = 0
    expiry_job_minute: int = 10
    default_rx_valid_days: int = 30  # until the branch's own setting has arrived
    # Create the private Rx file bucket at start-up when missing
    storage_bucket_check: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
