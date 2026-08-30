"""Database types that preserve MandateGuard invariants."""

from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import TypeDecorator

from mandateguard.core.time import normalize_utc


class UTCDateTime(TypeDecorator[datetime]):
    """Store UTC and always return timezone-aware UTC datetimes.

    SQLite drops timezone metadata, so values are stored there as naive UTC and have UTC
    restored when loaded. Other dialects receive an aware UTC value.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        normalized = normalize_utc(value)
        if dialect.name == "sqlite":
            return normalized.replace(tzinfo=None)
        return normalized

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        del dialect
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
