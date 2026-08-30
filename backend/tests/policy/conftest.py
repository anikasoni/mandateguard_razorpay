from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from mandateguard.domain import (
    Approval,
    ApprovalStatus,
    CheckoutAttempt,
    CheckoutStatus,
    EvaluationState,
    Mandate,
    MandateStatus,
    Product,
)

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)
DEFAULT_INTENT_HASH = "7bac3d1cf8b8c51e68500ecca2999a5c4ba6e8c1cd31e49581dfd036401b0339"


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def mandate_factory() -> Callable[..., Mandate]:
    def build(**changes: Any) -> Mandate:
        values: dict[str, Any] = {
            "mandate_id": "mandate-1",
            "status": MandateStatus.ACTIVE,
            "currency": "INR",
            "total_budget_paise": 100_000,
            "per_item_cap_paise": 20_000,
            "approval_threshold_paise": 15_000,
            "approved_merchants": frozenset({"acme"}),
            "approved_categories": frozenset({"office"}),
            "expires_at": NOW + timedelta(days=1),
        }
        values.update(changes)
        return Mandate(**values)

    return build


@pytest.fixture
def product_factory() -> Callable[..., Product]:
    def build(**changes: Any) -> Product:
        values: dict[str, Any] = {
            "product_id": "product-1",
            "merchant_id": "acme",
            "category_id": "office",
            "currency": "INR",
            "unit_price_paise": 5_000,
            "inventory_count": 20,
            "price_version": 7,
            "inventory_version": 4,
            "active": True,
            "offer_expires_at": NOW + timedelta(hours=1),
        }
        values.update(changes)
        return Product(**values)

    return build


@pytest.fixture
def request_factory() -> Callable[..., dict[str, Any]]:
    def build(tool: str = "create_checkout", **argument_changes: Any) -> dict[str, Any]:
        if tool == "get_product":
            arguments: dict[str, Any] = {"product_id": "product-1", "currency": "INR"}
        else:
            arguments = {
                "product_id": "product-1",
                "checkout_intent_id": "intent-1",
                "quantity": 2,
                "currency": "INR",
                "quoted_unit_price_paise": 5_000,
                "price_version": 7,
                "inventory_version": 4,
            }
            if tool == "present_offer":
                arguments["claims"] = {}
            elif "approval_id" not in argument_changes:
                arguments["approval_id"] = None
        arguments.update(argument_changes)
        return {
            "request_id": "request-1",
            "mandate_id": "mandate-1",
            "tool": tool,
            "arguments": arguments,
        }

    return build


@pytest.fixture
def state_factory(
    mandate_factory: Callable[..., Mandate], product_factory: Callable[..., Product]
) -> Callable[..., EvaluationState]:
    def build(**changes: Any) -> EvaluationState:
        values: dict[str, Any] = {
            "mandate": mandate_factory(),
            "products": (product_factory(),),
            "approvals": (),
            "checkout_attempts": (),
        }
        values.update(changes)
        return EvaluationState(**values)

    return build


@pytest.fixture
def approval_factory() -> Callable[..., Approval]:
    def build(**changes: Any) -> Approval:
        values: dict[str, Any] = {
            "approval_id": "approval-1",
            "mandate_id": "mandate-1",
            "checkout_intent_id": "intent-1",
            "request_hash": DEFAULT_INTENT_HASH,
            "amount_paise": 10_000,
            "currency": "INR",
            "status": ApprovalStatus.GRANTED,
            "expires_at": NOW + timedelta(hours=1),
        }
        values.update(changes)
        return Approval(**values)

    return build


@pytest.fixture
def attempt_factory() -> Callable[..., CheckoutAttempt]:
    def build(**changes: Any) -> CheckoutAttempt:
        values: dict[str, Any] = {
            "attempt_id": "attempt-1",
            "idempotency_key": "idem-1",
            "mandate_id": "mandate-1",
            "checkout_intent_id": "intent-1",
            "request_hash": DEFAULT_INTENT_HASH,
            "product_id": "product-1",
            "quantity": 2,
            "amount_paise": 10_000,
            "currency": "INR",
            "status": CheckoutStatus.COMPLETED,
            "reservation_expires_at": None,
        }
        values.update(changes)
        return CheckoutAttempt(**values)

    return build
