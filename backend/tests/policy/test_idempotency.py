from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from mandateguard.domain import CheckoutStatus, DecisionOutcome, EvaluationState, RuleId
from mandateguard.policy import PolicyEngine


def matching_attempt(
    attempt_factory: Callable[..., Any],
    **changes: Any,
) -> Any:
    return attempt_factory(**changes)


def test_exact_checkout_replays_without_new_spend_even_after_expiry(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    attempt_factory: Callable[..., Any],
    now: datetime,
) -> None:
    raw = request_factory()
    attempt = matching_attempt(attempt_factory)
    state = state_factory(checkout_attempts=(attempt,))
    decision = PolicyEngine().evaluate(raw, state, evaluated_at=now + timedelta(days=2))
    assert (decision.outcome, decision.rule_id, decision.execution_mode.value) == (
        DecisionOutcome.ALLOW,
        RuleId.INTENT_IDEMPOTENCY,
        "replay",
    )
    budget_evidence = decision.evidence[8]
    assert (
        next(fact.value for fact in budget_evidence.facts if fact.key == "projected_paise")
        == 10_000
    )


def test_same_intent_different_binding_is_conflict(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    attempt_factory: Callable[..., Any],
    now: datetime,
) -> None:
    decision = PolicyEngine().evaluate(
        request_factory(),
        state_factory(checkout_attempts=(attempt_factory(request_hash="f" * 64),)),
        evaluated_at=now,
    )
    assert (decision.rule_id, decision.reason) == (
        RuleId.INTENT_IDEMPOTENCY,
        "checkout_intent_conflict",
    )


def test_retryable_exact_attempt_returns_retry_mode(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    attempt_factory: Callable[..., Any],
    now: datetime,
) -> None:
    raw = request_factory()
    attempt = matching_attempt(attempt_factory, status=CheckoutStatus.RETRYABLE_FAILED)
    decision = PolicyEngine().evaluate(
        raw, state_factory(checkout_attempts=(attempt,)), evaluated_at=now
    )
    assert (
        decision.outcome,
        decision.rule_id,
        decision.execution_mode.value,
    ) == (
        DecisionOutcome.ALLOW,
        RuleId.AUTHORIZATION,
        "retry_existing",
    )


def test_retryable_attempt_does_not_bypass_expired_mandate(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    mandate_factory: Callable[..., Any],
    attempt_factory: Callable[..., Any],
    now: datetime,
) -> None:
    raw = request_factory()
    attempt = matching_attempt(attempt_factory, status=CheckoutStatus.RETRYABLE_FAILED)
    decision = PolicyEngine().evaluate(
        raw,
        state_factory(mandate=mandate_factory(expires_at=now), checkout_attempts=(attempt,)),
        evaluated_at=now,
    )
    assert (decision.outcome, decision.rule_id) == (
        DecisionOutcome.BLOCK,
        RuleId.MANDATE_STATUS,
    )


def test_retryable_attempt_does_not_bypass_stale_catalog(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    product_factory: Callable[..., Any],
    attempt_factory: Callable[..., Any],
    now: datetime,
) -> None:
    raw = request_factory()
    attempt = matching_attempt(attempt_factory, status=CheckoutStatus.RETRYABLE_FAILED)
    decision = PolicyEngine().evaluate(
        raw,
        state_factory(products=(product_factory(price_version=8),), checkout_attempts=(attempt,)),
        evaluated_at=now,
    )
    assert decision.rule_id is RuleId.CATALOG


def test_retryable_attempt_does_not_bypass_budget(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    attempt_factory: Callable[..., Any],
    now: datetime,
) -> None:
    raw = request_factory()
    retry = matching_attempt(attempt_factory, status=CheckoutStatus.RETRYABLE_FAILED)
    prior = attempt_factory(
        attempt_id="prior",
        idempotency_key="prior-key",
        checkout_intent_id="prior-intent",
        amount_paise=95_000,
    )
    decision = PolicyEngine().evaluate(
        raw, state_factory(checkout_attempts=(retry, prior)), evaluated_at=now
    )
    assert decision.rule_id is RuleId.CUMULATIVE_BUDGET


def test_retryable_attempt_does_not_bypass_approval(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    mandate_factory: Callable[..., Any],
    attempt_factory: Callable[..., Any],
    now: datetime,
) -> None:
    raw = request_factory()
    retry = matching_attempt(attempt_factory, status=CheckoutStatus.RETRYABLE_FAILED)
    decision = PolicyEngine().evaluate(
        raw,
        state_factory(
            mandate=mandate_factory(approval_threshold_paise=10_000),
            checkout_attempts=(retry,),
        ),
        evaluated_at=now,
    )
    assert (decision.outcome, decision.rule_id) == (
        DecisionOutcome.REQUEST_APPROVAL,
        RuleId.AUTHORIZATION,
    )


def test_active_retry_reservation_is_not_double_counted_and_reuses_consumed_approval(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    mandate_factory: Callable[..., Any],
    approval_factory: Callable[..., Any],
    attempt_factory: Callable[..., Any],
    now: datetime,
) -> None:
    raw = request_factory()
    consumed = approval_factory(status="consumed", approval_id="consumed-approval")
    retry = attempt_factory(
        status=CheckoutStatus.RETRYABLE_FAILED,
        reservation_expires_at=now + timedelta(minutes=1),
        approval_id="consumed-approval",
    )
    decision = PolicyEngine().evaluate(
        raw,
        state_factory(
            mandate=mandate_factory(
                total_budget_paise=10_000,
                per_item_cap_paise=10_000,
                approval_threshold_paise=10_000,
            ),
            approvals=(consumed,),
            checkout_attempts=(retry,),
        ),
        evaluated_at=now,
    )
    assert (decision.outcome, decision.execution_mode.value) == (
        DecisionOutcome.ALLOW,
        "retry_existing",
    )
    budget_facts = {fact.key: fact.value for fact in decision.evidence[8].facts}
    assert budget_facts["committed_paise"] == 10_000
    assert budget_facts["projected_paise"] == 10_000


def test_expired_retry_reservation_counts_proposed_spend_again(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    mandate_factory: Callable[..., Any],
    attempt_factory: Callable[..., Any],
    now: datetime,
) -> None:
    raw = request_factory()
    retry = matching_attempt(
        attempt_factory,
        status=CheckoutStatus.RETRYABLE_FAILED,
        reservation_expires_at=now,
    )
    decision = PolicyEngine().evaluate(
        raw,
        state_factory(
            mandate=mandate_factory(
                total_budget_paise=10_000,
                per_item_cap_paise=10_000,
                approval_threshold_paise=10_000,
            ),
            checkout_attempts=(retry,),
        ),
        evaluated_at=now,
    )
    assert decision.outcome is DecisionOutcome.REQUEST_APPROVAL
    budget_facts = {fact.key: fact.value for fact in decision.evidence[8].facts}
    assert budget_facts["committed_paise"] == 0
    assert budget_facts["projected_paise"] == 10_000


def test_terminal_failed_exact_attempt_blocks(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    attempt_factory: Callable[..., Any],
    now: datetime,
) -> None:
    raw = request_factory()
    attempt = matching_attempt(attempt_factory, status=CheckoutStatus.FAILED)
    decision = PolicyEngine().evaluate(
        raw, state_factory(checkout_attempts=(attempt,)), evaluated_at=now
    )
    assert decision.rule_id is RuleId.INTENT_IDEMPOTENCY
    assert decision.reason == "checkout_attempt_not_reusable"


def test_live_approval_with_different_binding_conflicts_for_same_intent(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    approval_factory: Callable[..., Any],
    now: datetime,
) -> None:
    raw = request_factory("request_approval", quantity=3)
    conflicting = approval_factory(status="pending", request_hash="f" * 64)
    decision = PolicyEngine().evaluate(
        raw, state_factory(approvals=(conflicting,)), evaluated_at=now
    )
    assert (decision.rule_id, decision.reason) == (
        RuleId.INTENT_IDEMPOTENCY,
        "approval_intent_conflict",
    )
