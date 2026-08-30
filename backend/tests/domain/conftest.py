from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from mandateguard.domain import CheckoutAttempt, CheckoutStatus, EvaluationState, Mandate, Product

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def product_factory() -> Callable[..., Product]:
    def build(**changes: Any) -> Product:
        values: dict[str, Any] = {
            "product_id": "product-1",
            "merchant_id": "acme",
            "category_id": "office",
            "currency": "INR",
            "unit_price_paise": 500,
            "inventory_count": 10,
            "price_version": 1,
            "inventory_version": 1,
            "active": True,
        }
        values.update(changes)
        return Product(**values)

    return build


@pytest.fixture
def state_factory(product_factory: Callable[..., Product]) -> Callable[..., EvaluationState]:
    def build(**changes: Any) -> EvaluationState:
        values: dict[str, Any] = {
            "mandate": Mandate(
                mandate_id="mandate-1",
                status="active",
                currency="INR",
                total_budget_paise=10_000,
                per_item_cap_paise=1_000,
                approval_threshold_paise=1_000,
                approved_merchants={"acme"},
                approved_categories={"office"},
                expires_at=NOW + timedelta(days=1),
            ),
            "products": (product_factory(),),
        }
        values.update(changes)
        return EvaluationState(**values)

    return build


@pytest.fixture
def attempt_factory() -> Callable[..., CheckoutAttempt]:
    def build(**changes: Any) -> CheckoutAttempt:
        values: dict[str, Any] = {
            "attempt_id": "attempt-1",
            "idempotency_key": "idem-1",
            "mandate_id": "mandate-1",
            "checkout_intent_id": "intent-1",
            "request_hash": "0" * 64,
            "product_id": "product-1",
            "quantity": 1,
            "amount_paise": 500,
            "currency": "INR",
            "status": CheckoutStatus.COMPLETED,
        }
        values.update(changes)
        return CheckoutAttempt(**values)

    return build
