"""Persistence integration fixtures."""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from mandateguard.db.base import Base
from mandateguard.db.session import create_database_engine, create_session_factory
from mandateguard.domain import Approval, CheckoutAttempt, Mandate, Product

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)
REQUEST_HASH = "7bac3d1cf8b8c51e68500ecca2999a5c4ba6e8c1cd31e49581dfd036401b0339"


@pytest.fixture
def persistence_engine() -> Generator[Engine, None, None]:
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER trg_audit_events_no_update "
            "BEFORE UPDATE ON audit_events BEGIN "
            "SELECT RAISE(ABORT, 'audit_events are append-only'); END"
        )
        connection.exec_driver_sql(
            "CREATE TRIGGER trg_audit_events_no_delete "
            "BEFORE DELETE ON audit_events BEGIN "
            "SELECT RAISE(ABORT, 'audit_events are append-only'); END"
        )
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def persistence_session_factory(
    persistence_engine: Engine,
) -> sessionmaker[Session]:
    return create_session_factory(persistence_engine)


@pytest.fixture
def mandate() -> Mandate:
    return Mandate(
        mandate_id="mandate-1",
        status="active",
        currency="INR",
        total_budget_paise=100_000,
        per_item_cap_paise=20_000,
        approval_threshold_paise=15_000,
        approved_merchants={"acme", "beta"},
        approved_categories={"office", "travel"},
        expires_at=NOW + timedelta(days=1),
    )


@pytest.fixture
def product() -> Product:
    return Product(
        product_id="product-1",
        merchant_id="acme",
        category_id="office",
        currency="INR",
        unit_price_paise=5_000,
        inventory_count=20,
        price_version=7,
        inventory_version=4,
        active=True,
        offer_expires_at=NOW + timedelta(hours=1),
    )


@pytest.fixture
def approval() -> Approval:
    return Approval(
        approval_id="approval-1",
        mandate_id="mandate-1",
        checkout_intent_id="intent-1",
        request_hash=REQUEST_HASH,
        amount_paise=10_000,
        currency="INR",
        status="granted",
        expires_at=NOW + timedelta(minutes=15),
    )


@pytest.fixture
def checkout_attempt() -> CheckoutAttempt:
    return CheckoutAttempt(
        attempt_id="attempt-1",
        idempotency_key="domain-permitted-idempotency-key",
        mandate_id="mandate-1",
        checkout_intent_id="intent-1",
        request_hash=REQUEST_HASH,
        product_id="product-1",
        quantity=2,
        amount_paise=10_000,
        currency="INR",
        status="reserved",
        reservation_expires_at=NOW + timedelta(minutes=5),
        approval_id="approval-1",
    )
