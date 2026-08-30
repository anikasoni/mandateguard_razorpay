"""Shared backend test fixtures."""

from collections.abc import Generator

import pytest

from mandateguard.core.config import get_settings


@pytest.fixture(autouse=True)
def reset_cached_state() -> Generator[None, None, None]:
    """Keep environment-backed settings isolated between tests."""

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
