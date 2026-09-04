"""SQLite BEGIN IMMEDIATE ownership and failure behavior."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from mandateguard.core.config import Settings
from mandateguard.db.base import Base
from mandateguard.db.models import AuditEventRecord, CheckoutAttemptRecord, MandateRecord
from mandateguard.db.repositories import MandateRepository, ProductRepository
from mandateguard.db.session import (
    FreshSessionRequiredError,
    create_database_engine,
    create_session_factory,
)
from mandateguard.domain import Mandate, Product
from mandateguard.services.policy import PolicyService


class FailingCommitSession(Session):
    close_called = False

    def commit(self) -> None:
        raise RuntimeError("injected commit failure")

    def close(self) -> None:
        FailingCommitSession.close_called = True
        super().close()


def test_begin_immediate_is_first_application_statement(
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
) -> None:
    with persistence_session_factory.begin() as session:
        MandateRepository(session).add(mandate)
        ProductRepository(session).add(product)
    statements: list[str] = []
    engine = persistence_session_factory.kw["bind"]

    def capture(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        del connection, cursor, parameters, context, executemany
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        PolicyService(persistence_session_factory, Settings(_env_file=None)).evaluate(
            {
                "request_id": "request-first-sql",
                "mandate_id": "mandate-1",
                "tool": "get_product",
                "arguments": {"product_id": "product-1", "currency": "INR"},
            },
            evaluated_at=datetime(2026, 8, 30, 12, tzinfo=mandate.expires_at.tzinfo),
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert statements[0] == "BEGIN IMMEDIATE"
    assert statements[1].lstrip().upper().startswith("SELECT")


def test_preused_session_from_factory_is_rejected_and_closed(
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
) -> None:
    session = persistence_session_factory()
    session.execute(select(MandateRecord))

    def preused_factory() -> Session:
        return session

    service = PolicyService(preused_factory, Settings(_env_file=None))  # type: ignore[arg-type]
    with pytest.raises(FreshSessionRequiredError):
        service.evaluate({}, evaluated_at=mandate.expires_at)
    assert not session.in_transaction()


def test_commit_failure_rolls_back_closes_and_returns_no_result(
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
) -> None:
    with persistence_session_factory.begin() as session:
        MandateRepository(session).add(mandate)
        ProductRepository(session).add(product)
    engine = persistence_session_factory.kw["bind"]
    failing_factory = sessionmaker(
        bind=engine,
        class_=FailingCommitSession,
        autoflush=False,
        expire_on_commit=False,
    )
    FailingCommitSession.close_called = False
    with pytest.raises(RuntimeError, match="injected commit failure"):
        PolicyService(failing_factory, Settings(_env_file=None)).evaluate(  # type: ignore[arg-type]
            {
                "request_id": "request-commit-failure",
                "mandate_id": "mandate-1",
                "tool": "create_checkout",
                "arguments": {
                    "product_id": "product-1",
                    "checkout_intent_id": "intent-commit-failure",
                    "quantity": 1,
                    "currency": "INR",
                    "quoted_unit_price_paise": 5_000,
                    "price_version": 7,
                    "inventory_version": 4,
                    "approval_id": None,
                },
            },
            evaluated_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
        )
    assert FailingCommitSession.close_called
    with persistence_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(CheckoutAttemptRecord)) == 0
        assert session.scalar(select(func.count()).select_from(AuditEventRecord)) == 0


def test_lock_timeout_raises_without_effect_or_audit(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{(tmp_path / 'locked.db').as_posix()}")

    @event.listens_for(engine, "checkout")
    def shorten_busy_timeout(
        dbapi_connection: object, connection_record: object, connection_proxy: object
    ) -> None:
        del connection_record, connection_proxy
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("PRAGMA busy_timeout=50")
        finally:
            cursor.close()

    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    mandate = Mandate(
        mandate_id="mandate-1",
        status="active",
        currency="INR",
        total_budget_paise=10_000,
        per_item_cap_paise=10_000,
        approval_threshold_paise=10_000,
        approved_merchants={"acme"},
        approved_categories={"office"},
        expires_at=datetime(2026, 8, 31, tzinfo=UTC),
    )
    product = Product(
        product_id="product-1",
        merchant_id="acme",
        category_id="office",
        currency="INR",
        unit_price_paise=5_000,
        inventory_count=1,
        price_version=1,
        inventory_version=1,
        active=True,
    )
    with factory.begin() as session:
        MandateRepository(session).add(mandate)
        ProductRepository(session).add(product)

    holder = engine.connect()
    holder.exec_driver_sql("BEGIN IMMEDIATE")
    try:
        with pytest.raises(OperationalError):
            PolicyService(factory, Settings(_env_file=None)).evaluate(
                {
                    "request_id": "request-locked",
                    "mandate_id": "mandate-1",
                    "tool": "get_product",
                    "arguments": {"product_id": "product-1", "currency": "INR"},
                },
                evaluated_at=datetime(2026, 8, 30, tzinfo=UTC),
            )
    finally:
        holder.rollback()
        holder.close()
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AuditEventRecord)) == 0
    engine.dispose()
