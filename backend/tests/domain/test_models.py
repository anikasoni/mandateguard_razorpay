from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from mandateguard.domain import CheckoutStatus, EvaluationState


def test_evaluation_state_has_deterministic_order(
    state_factory: Callable[..., EvaluationState],
    product_factory: Callable[..., Any],
) -> None:
    state = state_factory(
        products=(product_factory(product_id="z-product"), product_factory(product_id="a-product"))
    )
    assert [item.product_id for item in state.products] == ["a-product", "z-product"]


def test_reservation_spend_boundary_and_replay_are_distinct(
    now: datetime,
    state_factory: Callable[..., EvaluationState],
    attempt_factory: Callable[..., Any],
) -> None:
    expired = attempt_factory(
        status=CheckoutStatus.RESERVED,
        reservation_expires_at=now,
        amount_paise=500,
    )
    state = state_factory(checkout_attempts=(expired,))
    assert state.committed_spend_at("mandate-1", now) == 0
    assert expired.is_replayable_at(now + timedelta(days=1))
    assert not expired.retryable


def test_retryable_attempt_is_not_spend_and_is_retryable(
    now: datetime,
    attempt_factory: Callable[..., Any],
) -> None:
    attempt = attempt_factory(status=CheckoutStatus.RETRYABLE_FAILED)
    assert not attempt.contributes_spend_at(now)
    assert not attempt.is_replayable_at(now)
    assert attempt.retryable


@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_approval_ids_are_rejected_in_every_order(
    reverse: bool,
    state_factory: Callable[..., EvaluationState],
) -> None:
    from mandateguard.domain import Approval

    records = [
        Approval(
            approval_id="duplicate",
            mandate_id="mandate-1",
            checkout_intent_id="intent-1",
            request_hash="0" * 64,
            amount_paise=500,
            currency="INR",
            status=status,
            expires_at=datetime(2026, 9, 1, tzinfo=state_factory().mandate.expires_at.tzinfo),
        )
        for status in ("granted", "revoked")
    ]
    if reverse:
        records.reverse()
    with pytest.raises(ValidationError, match="approval IDs must be unique"):
        state_factory(approvals=tuple(records))


@pytest.mark.parametrize("field", ["attempt_id", "idempotency_key"])
@pytest.mark.parametrize("identical", [False, True])
def test_duplicate_attempt_identities_are_rejected(
    field: str,
    identical: bool,
    state_factory: Callable[..., EvaluationState],
    attempt_factory: Callable[..., Any],
) -> None:
    first = attempt_factory(attempt_id="first", idempotency_key="first-key")
    changes: dict[str, Any] = {
        "attempt_id": "second",
        "idempotency_key": "second-key",
        field: getattr(first, field),
    }
    if not identical:
        changes["amount_paise"] = 600
    second = first if identical else attempt_factory(**changes)
    with pytest.raises(ValidationError, match="must be unique"):
        state_factory(checkout_attempts=(first, second))


def test_duplicate_attempt_mandate_intent_identity_is_rejected(
    state_factory: Callable[..., EvaluationState],
    attempt_factory: Callable[..., Any],
) -> None:
    attempts = (
        attempt_factory(attempt_id="first", idempotency_key="first-key"),
        attempt_factory(attempt_id="second", idempotency_key="second-key"),
    )
    with pytest.raises(ValidationError, match="mandate/checkout-intent identities must be unique"):
        state_factory(checkout_attempts=attempts)


@given(order=st.permutations(("a", "b", "c")))
def test_unique_state_permutations_are_canonical(order: tuple[str, ...]) -> None:
    from datetime import UTC

    from mandateguard.domain import Mandate, Product

    mandate = Mandate(
        mandate_id="m",
        status="active",
        currency="INR",
        total_budget_paise=1_000,
        per_item_cap_paise=1_000,
        approval_threshold_paise=1_000,
        approved_merchants={"merchant"},
        approved_categories={"category"},
        expires_at=datetime(2030, 1, 1, tzinfo=UTC),
    )
    products = tuple(
        Product(
            product_id=item,
            merchant_id="merchant",
            category_id="category",
            currency="INR",
            unit_price_paise=100,
            inventory_count=1,
            price_version=1,
            inventory_version=1,
            active=True,
        )
        for item in order
    )
    state = EvaluationState(mandate=mandate, products=products)
    assert tuple(product.product_id for product in state.products) == ("a", "b", "c")
