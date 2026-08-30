from collections.abc import Callable
from datetime import datetime
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from mandateguard.domain import DecisionOutcome, EvaluationState, RuleId
from mandateguard.policy import PolicyEngine


def test_identical_input_state_and_time_produce_identical_decision(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    now: datetime,
) -> None:
    engine = PolicyEngine()
    raw = request_factory()
    state = state_factory()
    assert engine.evaluate(raw, state, evaluated_at=now) == engine.evaluate(
        raw, state, evaluated_at=now
    )


def test_request_id_does_not_change_fingerprint(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    now: datetime,
) -> None:
    first = request_factory()
    second = {**first, "request_id": "different-request-id"}
    engine = PolicyEngine()
    assert (
        engine.evaluate(first, state_factory(), evaluated_at=now).fingerprint
        == engine.evaluate(second, state_factory(), evaluated_at=now).fingerprint
    )


def test_approval_id_does_not_change_fingerprint(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    mandate_factory: Callable[..., Any],
    approval_factory: Callable[..., Any],
    now: datetime,
) -> None:
    first_request = request_factory(approval_id="approval-a")
    second_request = request_factory(approval_id="approval-b")
    mandate = mandate_factory(approval_threshold_paise=10_000)
    first_state = state_factory(
        mandate=mandate,
        approvals=(approval_factory(approval_id="approval-a"),),
    )
    second_state = state_factory(
        mandate=mandate,
        approvals=(approval_factory(approval_id="approval-b"),),
    )
    engine = PolicyEngine()
    assert (
        engine.evaluate(first_request, first_state, evaluated_at=now).fingerprint
        == engine.evaluate(second_request, second_state, evaluated_at=now).fingerprint
    )


def test_attempt_and_idempotency_ids_do_not_change_fingerprint(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    attempt_factory: Callable[..., Any],
    now: datetime,
) -> None:
    raw = request_factory()
    first = attempt_factory(attempt_id="attempt-a", idempotency_key="key-a")
    second = attempt_factory(attempt_id="attempt-b", idempotency_key="key-b")
    engine = PolicyEngine()
    assert (
        engine.evaluate(
            raw, state_factory(checkout_attempts=(first,)), evaluated_at=now
        ).fingerprint
        == engine.evaluate(
            raw, state_factory(checkout_attempts=(second,)), evaluated_at=now
        ).fingerprint
    )


@pytest.mark.parametrize(
    ("location", "field", "replacement"),
    [
        ("root", "mandate_id", "mandate-2"),
        ("arguments", "checkout_intent_id", "intent-2"),
        ("arguments", "product_id", "product-2"),
        ("arguments", "quantity", 3),
        ("arguments", "quoted_unit_price_paise", 5_001),
        ("arguments", "currency", "USD"),
        ("arguments", "price_version", 8),
        ("arguments", "inventory_version", 5),
    ],
)
def test_every_semantic_financial_change_changes_fingerprint(
    location: str,
    field: str,
    replacement: object,
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    mandate_factory: Callable[..., Any],
    product_factory: Callable[..., Any],
    now: datetime,
) -> None:
    baseline = PolicyEngine().evaluate(request_factory(), state_factory(), evaluated_at=now)
    raw = request_factory()
    state_changes: dict[str, Any] = {}
    product_changes: dict[str, Any] = {}
    if location == "root":
        raw[field] = replacement
        state_changes["mandate"] = mandate_factory(mandate_id=replacement)
    else:
        raw["arguments"][field] = replacement
        if field == "product_id":
            product_changes["product_id"] = replacement
        elif field == "quoted_unit_price_paise":
            product_changes["unit_price_paise"] = replacement
        elif field in {"currency", "price_version", "inventory_version"}:
            product_changes[field] = replacement
        if field == "currency":
            state_changes["mandate"] = mandate_factory(currency=replacement)
    if product_changes:
        state_changes["products"] = (product_factory(**product_changes),)
    changed = PolicyEngine().evaluate(
        raw,
        state_factory(**state_changes),
        evaluated_at=now,
    )
    assert changed.fingerprint != baseline.fingerprint


@given(order=st.permutations(("a", "b", "c")))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_unique_attempt_permutations_preserve_decision_and_fingerprint(
    order: tuple[str, ...],
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    attempt_factory: Callable[..., Any],
    now: datetime,
) -> None:
    attempts_by_id = {
        item: attempt_factory(
            attempt_id=f"attempt-{item}",
            idempotency_key=f"key-{item}",
            checkout_intent_id=f"prior-{item}",
            amount_paise=1_000,
        )
        for item in ("a", "b", "c")
    }
    baseline = PolicyEngine().evaluate(
        request_factory(),
        state_factory(checkout_attempts=tuple(attempts_by_id.values())),
        evaluated_at=now,
    )
    permuted = PolicyEngine().evaluate(
        request_factory(),
        state_factory(checkout_attempts=tuple(attempts_by_id[item] for item in order)),
        evaluated_at=now,
    )
    assert permuted == baseline


def test_state_insertion_order_does_not_change_fingerprint(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    approval_factory: Callable[..., Any],
    now: datetime,
) -> None:
    approvals = (
        approval_factory(
            approval_id="z-approval",
            mandate_id="other-mandate",
            checkout_intent_id="other-intent",
        ),
        approval_factory(
            approval_id="a-approval",
            mandate_id="other-mandate",
            checkout_intent_id="other-intent",
        ),
    )
    forward = PolicyEngine().evaluate(
        request_factory(), state_factory(approvals=approvals), evaluated_at=now
    )
    reverse = PolicyEngine().evaluate(
        request_factory(), state_factory(approvals=tuple(reversed(approvals))), evaluated_at=now
    )
    assert forward.fingerprint == reverse.fingerprint


def test_unrelated_approval_state_cannot_change_decision_or_fingerprint(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    approval_factory: Callable[..., Any],
    now: datetime,
) -> None:
    baseline = PolicyEngine().evaluate(request_factory(), state_factory(), evaluated_at=now)
    unrelated = approval_factory(
        mandate_id="other-mandate",
        checkout_intent_id="other-intent",
        status="revoked",
    )
    changed = PolicyEngine().evaluate(
        request_factory(), state_factory(approvals=(unrelated,)), evaluated_at=now
    )
    assert changed == baseline


def test_unrelated_mandate_spend_does_not_affect_budget(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    attempt_factory: Callable[..., Any],
    now: datetime,
) -> None:
    unrelated = attempt_factory(
        mandate_id="other-mandate",
        checkout_intent_id="other-intent",
        amount_paise=100_000,
    )
    decision = PolicyEngine().evaluate(
        request_factory(), state_factory(checkout_attempts=(unrelated,)), evaluated_at=now
    )
    assert decision.outcome is DecisionOutcome.ALLOW


def test_first_decisive_rule_wins_multiple_simultaneous_violations(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    now: datetime,
) -> None:
    raw = request_factory(currency="USD", price_version=99, approval_id="missing")
    decision = PolicyEngine().evaluate(raw, state_factory(), evaluated_at=now)
    assert decision.rule_id is RuleId.CURRENCY
    assert decision.evidence[4].reason == "catalog_state_stale_or_unavailable"
    assert decision.evidence[9].reason == "approval_missing"


def test_mg002_replay_precedes_expired_mandate(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    mandate_factory: Callable[..., Any],
    attempt_factory: Callable[..., Any],
    now: datetime,
) -> None:
    raw = request_factory()
    attempt = attempt_factory()
    decision = PolicyEngine().evaluate(
        raw,
        state_factory(mandate=mandate_factory(expires_at=now), checkout_attempts=(attempt,)),
        evaluated_at=now,
    )
    assert (decision.outcome, decision.rule_id) == (
        DecisionOutcome.ALLOW,
        RuleId.INTENT_IDEMPOTENCY,
    )
