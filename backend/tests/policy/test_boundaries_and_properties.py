from collections.abc import Callable
from datetime import datetime
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from mandateguard.domain import MAX_DB_INTEGER, DecisionOutcome, EvaluationState, RuleId
from mandateguard.policy import PolicyEngine


def test_transaction_total_overflow_is_mg001(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    product_factory: Callable[..., Any],
    mandate_factory: Callable[..., Any],
    now: datetime,
) -> None:
    raw = request_factory(quoted_unit_price_paise=MAX_DB_INTEGER, quantity=2)
    state = state_factory(
        mandate=mandate_factory(
            total_budget_paise=MAX_DB_INTEGER,
            per_item_cap_paise=MAX_DB_INTEGER,
            approval_threshold_paise=MAX_DB_INTEGER,
        ),
        products=(
            product_factory(
                unit_price_paise=MAX_DB_INTEGER,
                inventory_count=2,
            ),
        ),
    )
    decision = PolicyEngine().evaluate(raw, state, evaluated_at=now)
    assert (decision.rule_id, decision.reason) == (
        RuleId.REQUEST_CONTRACT,
        "transaction_total_overflow",
    )


def test_cumulative_addition_overflow_is_mg009(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    mandate_factory: Callable[..., Any],
    attempt_factory: Callable[..., Any],
    now: datetime,
) -> None:
    prior = attempt_factory(
        checkout_intent_id="prior", attempt_id="prior", amount_paise=MAX_DB_INTEGER
    )
    state = state_factory(
        mandate=mandate_factory(
            total_budget_paise=MAX_DB_INTEGER,
            per_item_cap_paise=20_000,
            approval_threshold_paise=15_000,
        ),
        checkout_attempts=(prior,),
    )
    decision = PolicyEngine().evaluate(request_factory(), state, evaluated_at=now)
    assert (decision.rule_id, decision.reason) == (
        RuleId.CUMULATIVE_BUDGET,
        "cumulative_spend_overflow",
    )


@given(
    price=st.integers(min_value=0, max_value=100_000),
    quantity=st.integers(min_value=1, max_value=100),
)
def test_projected_spend_at_budget_is_never_blocked_by_mg009(
    price: int,
    quantity: int,
) -> None:
    from datetime import UTC, timedelta

    from mandateguard.domain import Mandate, Product

    now = datetime(2026, 8, 30, tzinfo=UTC)
    total = price * quantity
    mandate = Mandate(
        mandate_id="m",
        status="active",
        currency="INR",
        total_budget_paise=total,
        per_item_cap_paise=price,
        approval_threshold_paise=total,
        approved_merchants={"merchant"},
        approved_categories={"category"},
        expires_at=now + timedelta(days=1),
    )
    product = Product(
        product_id="p",
        merchant_id="merchant",
        category_id="category",
        currency="INR",
        unit_price_paise=price,
        inventory_count=quantity,
        price_version=1,
        inventory_version=1,
        active=True,
    )
    raw = {
        "request_id": "r",
        "mandate_id": "m",
        "tool": "create_checkout",
        "arguments": {
            "product_id": "p",
            "checkout_intent_id": "i",
            "quantity": quantity,
            "currency": "INR",
            "quoted_unit_price_paise": price,
            "price_version": 1,
            "inventory_version": 1,
            "approval_id": None,
        },
    }
    decision = PolicyEngine().evaluate(
        raw, EvaluationState(mandate=mandate, products=(product,)), evaluated_at=now
    )
    assert decision.rule_id is not RuleId.CUMULATIVE_BUDGET
    assert decision.outcome in {DecisionOutcome.ALLOW, DecisionOutcome.REQUEST_APPROVAL}


@given(extra=st.integers(min_value=1, max_value=50_000))
def test_projected_spend_above_budget_always_blocks_mg009(extra: int) -> None:
    from datetime import UTC, timedelta

    from mandateguard.domain import Mandate, Product

    now = datetime(2026, 8, 30, tzinfo=UTC)
    mandate = Mandate(
        mandate_id="m",
        status="active",
        currency="INR",
        total_budget_paise=100_000,
        per_item_cap_paise=100_000,
        approval_threshold_paise=100_000,
        approved_merchants={"merchant"},
        approved_categories={"category"},
        expires_at=now + timedelta(days=1),
    )
    price = 50_000 + extra
    product = Product(
        product_id="p",
        merchant_id="merchant",
        category_id="category",
        currency="INR",
        unit_price_paise=price,
        inventory_count=2,
        price_version=1,
        inventory_version=1,
        active=True,
    )
    raw = {
        "request_id": "r",
        "mandate_id": "m",
        "tool": "present_offer",
        "arguments": {
            "product_id": "p",
            "checkout_intent_id": "i",
            "quantity": 2,
            "currency": "INR",
            "quoted_unit_price_paise": price,
            "price_version": 1,
            "inventory_version": 1,
            "claims": {},
        },
    }
    decision = PolicyEngine().evaluate(
        raw, EvaluationState(mandate=mandate, products=(product,)), evaluated_at=now
    )
    assert decision.rule_id is RuleId.CUMULATIVE_BUDGET
