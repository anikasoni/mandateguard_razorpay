"""Configuration tests."""

import pytest
from pydantic import ValidationError

from mandateguard.core.config import Settings


def test_settings_use_safe_local_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.environment == "development"
    assert settings.database_url == "sqlite+pysqlite:///./var/mandateguard.db"
    assert settings.pending_approval_ttl_seconds == 900
    assert settings.checkout_reservation_ttl_seconds == 300
    assert settings.human_approval_key is None
    assert settings.cors_origins == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_cors_origins_accept_comma_separated_environment_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "MANDATEGUARD_CORS_ORIGINS",
        "http://localhost:5173, https://review.example/",
    )

    settings = Settings(_env_file=None)

    assert settings.cors_origins == ["http://localhost:5173", "https://review.example"]


def test_cors_origins_reject_non_http_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANDATEGUARD_CORS_ORIGINS", "javascript:alert(1)")

    with pytest.raises(ValidationError, match="http:// or https://"):
        Settings(_env_file=None)


def test_human_approval_key_is_optional_but_rejects_short_values() -> None:
    assert Settings(_env_file=None, human_approval_key=None).human_approval_key is None
    with pytest.raises(ValidationError):
        Settings(_env_file=None, human_approval_key="too-short")


def test_razorpay_credentials_are_optional_or_a_complete_test_pair() -> None:
    assert Settings(_env_file=None).razorpay_configured is False
    configured = Settings(
        _env_file=None,
        razorpay_key_id="rzp_test_example",
        razorpay_key_secret="example-secret",
    )
    assert configured.razorpay_configured is True


@pytest.mark.parametrize(
    ("key_id", "key_secret"),
    [
        ("rzp_test_example", None),
        (None, "example-secret"),
        ("rzp_live_forbidden", "example-secret"),
    ],
)
def test_razorpay_credentials_reject_partial_or_live_configuration(
    key_id: str | None, key_secret: str | None
) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            razorpay_key_id=key_id,
            razorpay_key_secret=key_secret,
        )


@pytest.mark.parametrize(
    "name",
    [
        "MANDATEGUARD_PENDING_APPROVAL_TTL_SECONDS",
        "MANDATEGUARD_CHECKOUT_RESERVATION_TTL_SECONDS",
    ],
)
@pytest.mark.parametrize("value", ["0", "-1", "86401"])
def test_policy_ttls_are_positive_and_bounded(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
