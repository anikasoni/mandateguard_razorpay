"""Schema representation and field parity tests."""

from collections.abc import Mapping
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from mandateguard.db.mappers import (
    approval_from_record,
    approval_to_record,
    audit_record_from_decision,
    checkout_attempt_from_record,
    checkout_attempt_to_record,
    decision_from_audit_record,
    mandate_from_record,
    mandate_to_records,
    product_from_record,
    product_to_record,
)
from mandateguard.db.models import (
    ApprovalRecord,
    AuditEventRecord,
    CheckoutAttemptRecord,
    MandateCategoryScopeRecord,
    MandateMerchantScopeRecord,
    MandateRecord,
    ProductRecord,
)
from mandateguard.domain import Approval, CheckoutAttempt, EvaluationState, Mandate, Product
from mandateguard.policy import PolicyEngine


def _persist_prerequisites(
    session: Session, mandate: Mandate, product: Product
) -> tuple[
    MandateRecord,
    tuple[MandateMerchantScopeRecord, ...],
    tuple[MandateCategoryScopeRecord, ...],
]:
    mandate_parts = mandate_to_records(mandate)
    session.add(mandate_parts[0])
    session.flush()
    session.add_all((*mandate_parts[1], *mandate_parts[2]))
    session.add(product_to_record(product))
    session.flush()
    return mandate_parts


def test_mandate_field_parity(
    persistence_session_factory: sessionmaker[Session], mandate: Mandate
) -> None:
    assert set(Mandate.model_fields) == {
        "mandate_id",
        "status",
        "currency",
        "total_budget_paise",
        "per_item_cap_paise",
        "approval_threshold_paise",
        "approved_merchants",
        "approved_categories",
        "expires_at",
    }
    record, merchants, categories = mandate_to_records(mandate)
    with persistence_session_factory.begin() as session:
        session.add(record)
        session.flush()
        session.add_all((*merchants, *categories))
    with persistence_session_factory() as session:
        stored = session.get(MandateRecord, mandate.mandate_id)
        assert stored is not None
        stored_merchants = session.scalars(
            select(MandateMerchantScopeRecord).order_by(MandateMerchantScopeRecord.merchant_id)
        ).all()
        stored_categories = session.scalars(
            select(MandateCategoryScopeRecord).order_by(MandateCategoryScopeRecord.category_id)
        ).all()
        assert mandate_from_record(stored, stored_merchants, stored_categories) == mandate


def test_product_field_parity(
    persistence_session_factory: sessionmaker[Session], product: Product
) -> None:
    assert set(Product.model_fields) == {
        "product_id",
        "merchant_id",
        "category_id",
        "currency",
        "unit_price_paise",
        "inventory_count",
        "price_version",
        "inventory_version",
        "active",
        "offer_expires_at",
    }
    with persistence_session_factory.begin() as session:
        session.add(product_to_record(product))
    with persistence_session_factory() as session:
        stored = session.get(ProductRecord, product.product_id)
        assert stored is not None
        assert product_from_record(stored) == product


def test_approval_live_binding_is_not_a_domain_field(
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
    approval: Approval,
) -> None:
    assert set(Approval.model_fields) == {
        "approval_id",
        "mandate_id",
        "checkout_intent_id",
        "request_hash",
        "amount_paise",
        "currency",
        "status",
        "expires_at",
    }
    with persistence_session_factory.begin() as session:
        _persist_prerequisites(session, mandate, product)
        session.add(
            approval_to_record(approval, evaluated_at=datetime(2026, 8, 30, 12, tzinfo=UTC))
        )
    with persistence_session_factory() as session:
        stored = session.get(ApprovalRecord, approval.approval_id)
        assert stored is not None
        assert stored.live_binding == 1
        assert approval_from_record(stored) == approval


def test_checkout_attempt_field_parity(
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
    approval: Approval,
    checkout_attempt: CheckoutAttempt,
) -> None:
    assert set(CheckoutAttempt.model_fields) == {
        "attempt_id",
        "idempotency_key",
        "mandate_id",
        "checkout_intent_id",
        "request_hash",
        "product_id",
        "quantity",
        "amount_paise",
        "currency",
        "status",
        "reservation_expires_at",
        "approval_id",
    }
    with persistence_session_factory.begin() as session:
        _persist_prerequisites(session, mandate, product)
        session.add(
            approval_to_record(approval, evaluated_at=datetime(2026, 8, 30, 12, tzinfo=UTC))
        )
        session.add(checkout_attempt_to_record(checkout_attempt))
    with persistence_session_factory() as session:
        stored = session.get(CheckoutAttemptRecord, checkout_attempt.attempt_id)
        assert stored is not None
        assert checkout_attempt_from_record(stored) == checkout_attempt


def test_guard_decision_audit_field_parity(
    persistence_session_factory: sessionmaker[Session], mandate: Mandate, product: Product
) -> None:
    raw: dict[str, object] = {
        "request_id": "request-1",
        "mandate_id": "mandate-1",
        "tool": "get_product",
        "arguments": {"product_id": "product-1", "currency": "INR"},
    }
    decision = PolicyEngine().evaluate(
        raw,
        EvaluationState(mandate=mandate, products=(product,)),
        evaluated_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
    )
    arguments = raw["arguments"]
    assert isinstance(arguments, Mapping)
    record = audit_record_from_decision(event_id="audit-1", decision=decision, arguments=arguments)
    with persistence_session_factory.begin() as session:
        _persist_prerequisites(session, mandate, product)
        session.add(record)
    with persistence_session_factory() as session:
        stored = session.get(AuditEventRecord, "audit-1")
        assert stored is not None
        assert decision_from_audit_record(stored) == decision


@pytest.mark.parametrize(
    ("table", "column", "value"),
    [
        ("products", "unit_price_paise", 1.5),
        ("products", "inventory_count", -1),
        ("products", "price_version", 1.25),
    ],
)
def test_sqlite_checks_final_integer_storage_and_bounds(
    persistence_engine: Engine, table: str, column: str, value: object
) -> None:
    assert table == "products"
    with persistence_engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            insert(ProductRecord).values(
                product_id="bad-product",
                merchant_id="acme",
                category_id="office",
                currency="INR",
                unit_price_paise=value if column == "unit_price_paise" else 1,
                inventory_count=value if column == "inventory_count" else 1,
                price_version=value if column == "price_version" else 1,
                inventory_version=1,
                active=True,
            )
        )


def test_sqlite_numeric_string_affinity_is_documented(persistence_engine: Engine) -> None:
    with persistence_engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO products "
            "(product_id, merchant_id, category_id, currency, unit_price_paise, "
            "inventory_count, price_version, inventory_version, active) "
            "VALUES ('string-price', 'acme', 'office', 'INR', '10', 1, 1, 1, 1)"
        )
        storage_class = connection.execute(
            text("SELECT typeof(unit_price_paise) FROM products WHERE product_id='string-price'")
        ).scalar_one()
    assert storage_class == "integer"


def test_currency_is_inr_only(persistence_engine: Engine) -> None:
    with persistence_engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            insert(ProductRecord).values(
                product_id="usd-product",
                merchant_id="acme",
                category_id="office",
                currency="USD",
                unit_price_paise=1,
                inventory_count=1,
                price_version=1,
                inventory_version=1,
                active=True,
            )
        )


def test_live_binding_requires_exact_zero_or_one(
    persistence_engine: Engine, mandate: Mandate, product: Product
) -> None:
    with Session(persistence_engine) as session, session.begin():
        _persist_prerequisites(session, mandate, product)
    with persistence_engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            insert(ApprovalRecord).values(
                approval_id="approval-bad-live",
                mandate_id="mandate-1",
                checkout_intent_id="intent-live",
                request_hash="0" * 64,
                amount_paise=1,
                currency="INR",
                status="pending",
                expires_at=datetime(2026, 9, 1, tzinfo=UTC),
                live_binding=2,
            )
        )
