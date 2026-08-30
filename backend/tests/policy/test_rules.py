from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import pytest

from mandateguard.domain import (
    DecisionOutcome,
    EvaluationState,
    MandateStatus,
    RuleId,
)
from mandateguard.policy import PolicyEngine


@pytest.mark.parametrize(
    ("rule_id", "request_changes", "reason"),
    [
        (RuleId.CURRENCY, {"currency": "USD"}, "currency_mismatch_or_unsupported"),
        (RuleId.CATALOG, {"price_version": 6}, "catalog_state_stale_or_unavailable"),
        (RuleId.PER_ITEM_CAP, {"quoted_unit_price_paise": 20_001}, "per_item_cap_exceeded"),
    ],
)
def test_financial_rule_failures(
    rule_id: RuleId,
    request_changes: dict[str, Any],
    reason: str,
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    product_factory: Callable[..., Any],
    now: datetime,
) -> None:
    if rule_id is RuleId.PER_ITEM_CAP:
        state = state_factory(products=(product_factory(unit_price_paise=20_001),))
    else:
        state = state_factory()
    decision = PolicyEngine().evaluate(
        request_factory("create_checkout", **request_changes), state, evaluated_at=now
    )
    assert (decision.outcome, decision.rule_id, decision.reason) == (
        DecisionOutcome.BLOCK,
        rule_id,
        reason,
    )


def test_mandate_status_and_expiry_boundary_are_mg003(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    mandate_factory: Callable[..., Any],
    now: datetime,
) -> None:
    for mandate in (
        mandate_factory(status=MandateStatus.REVOKED),
        mandate_factory(expires_at=now),
    ):
        decision = PolicyEngine().evaluate(
            request_factory("get_product"), state_factory(mandate=mandate), evaluated_at=now
        )
        assert decision.rule_id is RuleId.MANDATE_STATUS


def test_catalog_inventory_and_active_state_are_mg005(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    product_factory: Callable[..., Any],
    now: datetime,
) -> None:
    for product in (product_factory(active=False), product_factory(inventory_count=1)):
        decision = PolicyEngine().evaluate(
            request_factory(), state_factory(products=(product,)), evaluated_at=now
        )
        assert decision.rule_id is RuleId.CATALOG


def test_merchant_and_category_use_exact_and_semantics(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    product_factory: Callable[..., Any],
    now: datetime,
) -> None:
    for product in (
        product_factory(merchant_id="other"),
        product_factory(category_id="travel"),
    ):
        decision = PolicyEngine().evaluate(
            request_factory("get_product"), state_factory(products=(product,)), evaluated_at=now
        )
        assert decision.rule_id is RuleId.SCOPE


def test_cumulative_budget_includes_completed_and_live_reservations_only(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    attempt_factory: Callable[..., Any],
    now: datetime,
) -> None:
    attempts = (
        attempt_factory(
            attempt_id="complete",
            idempotency_key="complete-key",
            checkout_intent_id="other-0",
            amount_paise=85_000,
        ),
        attempt_factory(
            attempt_id="live",
            idempotency_key="live-key",
            checkout_intent_id="other-1",
            status="reserved",
            reservation_expires_at=now + timedelta(seconds=1),
            amount_paise=6_000,
        ),
        attempt_factory(
            attempt_id="expired",
            idempotency_key="expired-key",
            checkout_intent_id="other-2",
            status="reserved",
            reservation_expires_at=now,
            amount_paise=99_000,
        ),
    )
    decision = PolicyEngine().evaluate(
        request_factory(), state_factory(checkout_attempts=attempts), evaluated_at=now
    )
    assert decision.rule_id is RuleId.CUMULATIVE_BUDGET
    assert decision.reason == "cumulative_budget_exceeded"


def test_budget_equality_is_allowed(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    attempt_factory: Callable[..., Any],
    now: datetime,
) -> None:
    prior = attempt_factory(
        checkout_intent_id="prior", amount_paise=90_000, attempt_id="prior-attempt"
    )
    decision = PolicyEngine().evaluate(
        request_factory(), state_factory(checkout_attempts=(prior,)), evaluated_at=now
    )
    assert decision.outcome is DecisionOutcome.ALLOW


def test_mandate_is_valid_immediately_before_expiry(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    mandate_factory: Callable[..., Any],
    now: datetime,
) -> None:
    mandate = mandate_factory(expires_at=now + timedelta(microseconds=1))
    decision = PolicyEngine().evaluate(
        request_factory("get_product"), state_factory(mandate=mandate), evaluated_at=now
    )
    assert decision.outcome is DecisionOutcome.ALLOW
