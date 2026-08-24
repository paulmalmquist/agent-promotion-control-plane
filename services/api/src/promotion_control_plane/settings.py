from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://promotion:promotion@localhost:5433/promotion_control_plane"
    )
    startup_bootstrap: bool = False
    demo_mode: bool = True
    config_root: str = "/app/configs"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3001"
    worker_id: str = "promotion-worker"
    worker_poll_seconds: float = 0.5
    worker_lease_seconds: int = 30
    worker_max_attempts: int = 3
    openai_api_key: str | None = Field(default=None, repr=False)
    openai_eval_model: str = "gpt-5-mini"
    event_keepalive_seconds: int = 15
    event_poll_seconds: float = 0.5


@lru_cache
def get_settings() -> Settings:
    return Settings()
