"""Two-connection SQLite policy concurrency tests."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Lock

from sqlalchemy import Engine, event, func, select
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from mandateguard.core.config import Settings
from mandateguard.db.base import Base
from mandateguard.db.models import ApprovalRecord, AuditEventRecord, CheckoutAttemptRecord
from mandateguard.db.repositories import MandateRepository, ProductRepository
from mandateguard.db.session import create_database_engine, create_session_factory
from mandateguard.domain import DecisionOutcome, Mandate, Product, RuleId
from mandateguard.services.policy import PolicyService, PolicyServiceResult

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)


def _file_service(
    tmp_path: Path, mandate: Mandate, product: Product
) -> tuple[PolicyService, Engine]:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'concurrency.db').as_posix()}"
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with factory.begin() as session:
        MandateRepository(session).add(mandate)
        ProductRepository(session).add(product)
    return PolicyService(factory, Settings(_env_file=None)), engine


def _approval_request() -> dict[str, object]:
    return {
        "request_id": "approval-request",
        "mandate_id": "mandate-1",
        "tool": "request_approval",
        "arguments": {
            "product_id": "product-1",
            "checkout_intent_id": "intent-approval",
            "quantity": 1,
            "currency": "INR",
            "quoted_unit_price_paise": 6_000,
            "price_version": 1,
            "inventory_version": 1,
            "approval_id": None,
        },
    }


def _checkout_request(intent_id: str) -> dict[str, object]:
    return {
        "request_id": f"request-{intent_id}",
        "mandate_id": "mandate-1",
        "tool": "create_checkout",
        "arguments": {
            "product_id": "product-1",
            "checkout_intent_id": intent_id,
            "quantity": 1,
            "currency": "INR",
            "quoted_unit_price_paise": 6_000,
            "price_version": 1,
            "inventory_version": 1,
            "approval_id": None,
        },
    }


def _run_with_proven_contention(
    service: PolicyService,
    engine: Engine,
    requests: tuple[dict[str, object], dict[str, object]],
) -> tuple[PolicyServiceResult, PolicyServiceResult]:
    """Hold the first write transaction until the second physical connection blocks on BEGIN."""

    first_acquired = Event()
    second_attempting = Event()
    release_first = Event()
    guard = Lock()
    begin_attempt_connection_ids: list[int] = []
    begin_acquired_connection_ids: list[int] = []

    def connection_id(connection: Connection) -> int:
        fairy = connection.connection
        return id(fairy.driver_connection)

    def before_cursor_execute(
        connection: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        del cursor, parameters, context, executemany
        if statement.strip().upper() != "BEGIN IMMEDIATE":
            return
        with guard:
            begin_attempt_connection_ids.append(connection_id(connection))
            if len(begin_attempt_connection_ids) == 2:
                second_attempting.set()

    def after_cursor_execute(
        connection: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        del cursor, parameters, context, executemany
        if statement.strip().upper() != "BEGIN IMMEDIATE":
            return
        with guard:
            begin_acquired_connection_ids.append(connection_id(connection))
            is_first = len(begin_acquired_connection_ids) == 1
        if is_first:
            first_acquired.set()
            if not release_first.wait(timeout=10):
                raise TimeoutError("test did not release the first SQLite write transaction")

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    event.listen(engine, "after_cursor_execute", after_cursor_execute)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(service.evaluate, requests[0], evaluated_at=NOW)
            assert first_acquired.wait(timeout=5)
            second_future = executor.submit(service.evaluate, requests[1], evaluated_at=NOW)
            assert second_attempting.wait(timeout=5)
            assert len(begin_attempt_connection_ids) == 2
            assert begin_attempt_connection_ids[0] != begin_attempt_connection_ids[1]
            assert not second_future.done()
            assert begin_acquired_connection_ids == [begin_attempt_connection_ids[0]]
            release_first.set()
            first = first_future.result(timeout=10)
            second = second_future.result(timeout=10)
    finally:
        release_first.set()
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
        event.remove(engine, "after_cursor_execute", after_cursor_execute)

    assert begin_acquired_connection_ids == begin_attempt_connection_ids
    return first, second


def test_concurrent_identical_approval_requests_create_once_and_replay(
    tmp_path: Path,
) -> None:
    mandate = Mandate(
        mandate_id="mandate-1",
        status="active",
        currency="INR",
        total_budget_paise=20_000,
        per_item_cap_paise=10_000,
        approval_threshold_paise=6_000,
        approved_merchants={"acme"},
        approved_categories={"office"},
        expires_at=NOW + timedelta(days=1),
    )
    product = Product(
        product_id="product-1",
        merchant_id="acme",
        category_id="office",
        currency="INR",
        unit_price_paise=6_000,
        inventory_count=2,
        price_version=1,
        inventory_version=1,
        active=True,
    )
    service, engine = _file_service(tmp_path, mandate, product)
    try:
        first, second = _run_with_proven_contention(
            service, engine, (_approval_request(), _approval_request())
        )
        assert {first.decision.execution_mode.value, second.decision.execution_mode.value} == {
            "execute",
            "replay",
        }
        assert first.approval == second.approval
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(ApprovalRecord)) == 1
            assert session.scalar(select(func.count()).select_from(AuditEventRecord)) == 2
    finally:
        engine.dispose()


def test_concurrent_distinct_intents_cannot_oversubscribe_budget(tmp_path: Path) -> None:
    mandate = Mandate(
        mandate_id="mandate-1",
        status="active",
        currency="INR",
        total_budget_paise=10_000,
        per_item_cap_paise=10_000,
        approval_threshold_paise=10_000,
        approved_merchants={"acme"},
        approved_categories={"office"},
        expires_at=NOW + timedelta(days=1),
    )
    product = Product(
        product_id="product-1",
        merchant_id="acme",
        category_id="office",
        currency="INR",
        unit_price_paise=6_000,
        inventory_count=2,
        price_version=1,
        inventory_version=1,
        active=True,
    )
    service, engine = _file_service(tmp_path, mandate, product)
    try:
        results = _run_with_proven_contention(
            service,
            engine,
            (_checkout_request("intent-a"), _checkout_request("intent-b")),
        )
        assert {item.decision.outcome for item in results} == {
            DecisionOutcome.ALLOW,
            DecisionOutcome.BLOCK,
        }
        blocked = next(item for item in results if item.decision.outcome is DecisionOutcome.BLOCK)
        assert blocked.decision.rule_id is RuleId.CUMULATIVE_BUDGET
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(CheckoutAttemptRecord)) == 1
            assert session.scalar(select(func.count()).select_from(AuditEventRecord)) == 2
    finally:
        engine.dispose()


def test_concurrent_identical_checkout_requests_create_once_and_replay(tmp_path: Path) -> None:
    mandate = Mandate(
        mandate_id="mandate-1",
        status="active",
        currency="INR",
        total_budget_paise=20_000,
        per_item_cap_paise=10_000,
        approval_threshold_paise=10_000,
        approved_merchants={"acme"},
        approved_categories={"office"},
        expires_at=NOW + timedelta(days=1),
    )
    product = Product(
        product_id="product-1",
        merchant_id="acme",
        category_id="office",
        currency="INR",
        unit_price_paise=6_000,
        inventory_count=2,
        price_version=1,
        inventory_version=1,
        active=True,
    )
    service, engine = _file_service(tmp_path, mandate, product)
    try:
        request = _checkout_request("intent-shared")
        first, second = _run_with_proven_contention(service, engine, (request, request))
        assert {first.decision.execution_mode.value, second.decision.execution_mode.value} == {
            "execute",
            "replay",
        }
        assert first.checkout_attempt == second.checkout_attempt
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(CheckoutAttemptRecord)) == 1
            assert session.scalar(select(func.count()).select_from(AuditEventRecord)) == 2
    finally:
        engine.dispose()
