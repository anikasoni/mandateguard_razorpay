"""Environment-backed application configuration."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
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
    frontend_dist_dir: Path | None = None
    pending_approval_ttl_seconds: int = Field(default=900, ge=1, le=86_400)
    checkout_reservation_ttl_seconds: int = Field(default=300, ge=1, le=86_400)
    human_approval_key: SecretStr | None = Field(default=None, min_length=16)
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.1-flash-lite"
    razorpay_key_id: str | None = Field(default=None, min_length=8)
    razorpay_key_secret: SecretStr | None = Field(default=None, min_length=8)
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @property
    def razorpay_configured(self) -> bool:
        """Return whether both credentials required for test-mode Orders exist."""

        return self.razorpay_key_id is not None and self.razorpay_key_secret is not None

    @model_validator(mode="after")
    def require_test_mode_razorpay_pair(self) -> Self:
        """Accept only a complete Razorpay test-key pair."""

        configured = (self.razorpay_key_id is not None, self.razorpay_key_secret is not None)
        if configured[0] != configured[1]:
            raise ValueError("Razorpay key ID and secret must be configured together")
        if self.razorpay_key_id is not None and not self.razorpay_key_id.startswith("rzp_test_"):
            raise ValueError("only Razorpay test-mode key IDs are accepted")
        return self

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
