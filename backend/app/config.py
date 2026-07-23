from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Taskman"
    environment: str = "development"
    database_url: str = "sqlite:///./data/taskman.db"
    vault_path: Path = Path("./data/vault")
    cors_origins: str = (
        "http://localhost:1420,http://127.0.0.1:1420,"
        "tauri://localhost,http://tauri.localhost,https://tauri.localhost"
    )
    public_url: str = "http://127.0.0.1:8765"
    jwt_secret: str = Field(default="development-secret-change-me-at-least-32-bytes", min_length=32)
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    setup_token: str | None = None
    encryption_key: str | None = None
    max_attachment_mb: int = 25
    telegram_poll_seconds: float = 1.0
    telegram_polling_enabled: bool = False
    ai_enabled: bool = False
    ai_api_key: str | None = None
    ai_base_url: str = "https://api.openai.com/v1"
    ai_model: str = "gpt-4o-mini"

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_prefix="TASKMAN_",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
