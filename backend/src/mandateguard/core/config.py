"""Environment-backed application configuration."""

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables or a local `.env` file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MANDATEGUARD_",
        case_sensitive=False,
        extra="ignore",
        enable_decoding=False,
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite+pysqlite:///./var/mandateguard.db"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        """Accept a comma-separated environment value while retaining a typed list."""

        if isinstance(value, str):
            origins = [origin.strip().rstrip("/") for origin in value.split(",")]
            return [origin for origin in origins if origin]
        return value

    @field_validator("cors_origins")
    @classmethod
    def require_cors_origins(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("at least one CORS origin is required")
        if any(not origin.startswith(("http://", "https://")) for origin in value):
            raise ValueError("CORS origins must use http:// or https://")
        return value


@lru_cache
def get_settings() -> Settings:
    """Return one immutable-by-convention settings instance per process."""

    return Settings()
