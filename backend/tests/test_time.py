"""UTC utility tests."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from mandateguard.core.time import normalize_utc, utc_now


def test_utc_now_is_aware_utc() -> None:
    value = utc_now()

    assert value.tzinfo is UTC
    assert value.utcoffset() == timedelta(0)


def test_normalize_utc_converts_an_aware_value() -> None:
    source = datetime(2026, 8, 29, 17, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))

    assert normalize_utc(source) == datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def test_normalize_utc_rejects_naive_values() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        normalize_utc(datetime(2026, 8, 29, 12, 0))
