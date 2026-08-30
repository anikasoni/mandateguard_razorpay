"""SQLite and custom database type tests."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, insert, select, text
from sqlalchemy.exc import StatementError

from mandateguard.db.session import create_database_engine
from mandateguard.db.types import UTCDateTime


def test_sqlite_engine_enables_foreign_keys_and_busy_timeout() -> None:
    engine = create_database_engine("sqlite+pysqlite:///:memory:")

    try:
        with engine.connect() as connection:
            foreign_keys = connection.execute(text("PRAGMA foreign_keys")).scalar_one()
            busy_timeout = connection.execute(text("PRAGMA busy_timeout")).scalar_one()
    finally:
        engine.dispose()

    assert foreign_keys == 1
    assert busy_timeout == 5000


def test_utc_datetime_round_trips_as_aware_utc() -> None:
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    metadata = MetaData()
    events = Table(
        "test_events",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("occurred_at", UTCDateTime(), nullable=False),
    )
    metadata.create_all(engine)
    source = datetime(2026, 8, 29, 17, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))

    try:
        with engine.begin() as connection:
            connection.execute(insert(events).values(occurred_at=source))
        with engine.connect() as connection:
            stored = connection.execute(select(events.c.occurred_at)).scalar_one()
    finally:
        engine.dispose()

    assert stored == datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    assert stored.tzinfo is UTC


def test_utc_datetime_rejects_naive_values() -> None:
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    metadata = MetaData()
    events = Table(
        "test_events",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("occurred_at", UTCDateTime(), nullable=False),
    )
    metadata.create_all(engine)

    try:
        with pytest.raises(StatementError, match="timezone-aware"), engine.begin() as connection:
            connection.execute(insert(events).values(occurred_at=datetime(2026, 8, 29, 12, 0)))
    finally:
        engine.dispose()
