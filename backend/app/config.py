import secrets
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


_EPHEMERAL_DEVELOPMENT_JWT_SECRET = secrets.token_urlsafe(48)


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
    jwt_secret: str | None = Field(default=None, min_length=32)
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    setup_token: str | None = None
    encryption_key: str | None = None
    max_attachment_mb: int = 25
    max_request_mb: int = Field(default=30, ge=1, le=1024)
    telegram_poll_seconds: float = 1.0
    telegram_polling_enabled: bool = False
    integration_poll_seconds: float = Field(default=5.0, ge=0.5, le=300)
    max_api_tls_verify: bool = True
    trusted_hosts: str = "localhost,127.0.0.1,testserver"
    login_max_attempts: int = Field(default=8, ge=3, le=100)
    login_window_seconds: int = Field(default=300, ge=30, le=86400)
    bind_host: str = "127.0.0.1"
    bind_port: int = Field(default=8765, ge=1, le=65535)

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_prefix="TASKMAN_",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def trusted_host_list(self) -> list[str]:
        return [item.strip() for item in self.trusted_hosts.split(",") if item.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.casefold() in {"production", "prod"}

    @property
    def effective_jwt_secret(self) -> str:
        return self.jwt_secret or _EPHEMERAL_DEVELOPMENT_JWT_SECRET

    def validate_runtime(self) -> None:
        """Fail closed when a public deployment still uses development defaults."""
        if self.max_request_mb < self.max_attachment_mb:
            raise RuntimeError(
                "TASKMAN_MAX_REQUEST_MB must be greater than or equal to "
                "TASKMAN_MAX_ATTACHMENT_MB"
            )
        if not self.is_production:
            return
        errors: list[str] = []
        if not self.jwt_secret:
            errors.append("TASKMAN_JWT_SECRET is required")
        if not self.setup_token or len(self.setup_token) < 32:
            errors.append("TASKMAN_SETUP_TOKEN must contain at least 32 characters")
        if not self.encryption_key:
            errors.append("TASKMAN_ENCRYPTION_KEY is required")
        else:
            try:
                Fernet(self.encryption_key.encode("ascii"))
            except (UnicodeEncodeError, ValueError):
                errors.append("TASKMAN_ENCRYPTION_KEY must be a valid Fernet key")
        if urlparse(self.public_url).scheme != "https":
            errors.append("TASKMAN_PUBLIC_URL must use HTTPS")
        if "*" in self.cors_origin_list:
            errors.append("TASKMAN_CORS_ORIGINS must not contain '*'")
        if not self.trusted_host_list or "*" in self.trusted_host_list:
            errors.append("TASKMAN_TRUSTED_HOSTS must explicitly list allowed hosts")
        if errors:
            raise RuntimeError("Unsafe production configuration:\n- " + "\n- ".join(errors))


@lru_cache
def get_settings() -> Settings:
    return Settings()
