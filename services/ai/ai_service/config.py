from functools import lru_cache

from pharmacy_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "ai"
    api_prefix: str = "/api/ai/v1"
    db_name: str = "pharmacy_ai"
    db_user: str = "ai_user"
    db_password: str = "change-me-ai"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model_fast: str = "deepseek-flash"
    deepseek_model_reasoning: str = "deepseek-v4-pro"


@lru_cache
def get_settings() -> Settings:
    return Settings()
