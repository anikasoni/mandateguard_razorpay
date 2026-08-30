from collections.abc import Callable
from datetime import datetime
from typing import Any

import pytest

from mandateguard.domain import ApprovalStatus, DecisionOutcome, EvaluationState, RuleId
from mandateguard.policy import PolicyEngine


def bound_approval(
    approval_factory: Callable[..., Any],
    **changes: Any,
) -> Any:
    return approval_factory(**changes)


def test_threshold_equality_requires_approval_for_checkout(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    mandate_factory: Callable[..., Any],
    now: datetime,
) -> None:
    state = state_factory(mandate=mandate_factory(approval_threshold_paise=10_000))
    decision = PolicyEngine().evaluate(request_factory(), state, evaluated_at=now)
    assert (decision.outcome, decision.rule_id) == (
        DecisionOutcome.REQUEST_APPROVAL,
        RuleId.AUTHORIZATION,
    )


def test_checkout_below_threshold_allows_without_approval(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    now: datetime,
) -> None:
    decision = PolicyEngine().evaluate(request_factory(), state_factory(), evaluated_at=now)
    assert decision.outcome is DecisionOutcome.ALLOW


def test_request_approval_below_threshold_is_blocked(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    now: datetime,
) -> None:
    decision = PolicyEngine().evaluate(
        request_factory("request_approval"), state_factory(), evaluated_at=now
    )
    assert (decision.outcome, decision.reason) == (
        DecisionOutcome.BLOCK,
        "approval_not_required",
    )


def test_request_approval_at_threshold_allows_creation_or_pending_replay(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    mandate_factory: Callable[..., Any],
    approval_factory: Callable[..., Any],
    now: datetime,
) -> None:
    raw = request_factory("request_approval")
    mandate = mandate_factory(approval_threshold_paise=10_000)
    first = PolicyEngine().evaluate(raw, state_factory(mandate=mandate), evaluated_at=now)
    assert first.reason == "approval_creation_allowed"
    approval = bound_approval(approval_factory, status=ApprovalStatus.PENDING)
    replay = PolicyEngine().evaluate(
        raw, state_factory(mandate=mandate, approvals=(approval,)), evaluated_at=now
    )
    assert replay.reason == "approval_request_replayed"
    assert replay.execution_mode.value == "replay"


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"status": ApprovalStatus.CONSUMED}, "approval_status_invalid"),
        ({"status": ApprovalStatus.REVOKED}, "approval_status_invalid"),
        ({"status": ApprovalStatus.REJECTED}, "approval_status_invalid"),
        ({"request_hash": "f" * 64}, "approval_binding_mismatch"),
        ({"amount_paise": 9_999}, "approval_binding_mismatch"),
    ],
)
def test_invalid_supplied_approval_always_blocks_mg010(
    changes: dict[str, Any],
    reason: str,
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    approval_factory: Callable[..., Any],
    now: datetime,
) -> None:
    raw = request_factory(approval_id="approval-1")
    approval = bound_approval(approval_factory, **changes)
    decision = PolicyEngine().evaluate(raw, state_factory(approvals=(approval,)), evaluated_at=now)
    assert (decision.rule_id, decision.reason) == (RuleId.APPROVAL, reason)


def test_expired_approval_and_missing_approval_block_mg010(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    approval_factory: Callable[..., Any],
    now: datetime,
) -> None:
    raw = request_factory(approval_id="approval-1")
    expired = bound_approval(approval_factory, expires_at=now)
    for approvals, reason in (((expired,), "approval_expired"), ((), "approval_missing")):
        decision = PolicyEngine().evaluate(
            raw, state_factory(approvals=approvals), evaluated_at=now
        )
        assert (decision.rule_id, decision.reason) == (RuleId.APPROVAL, reason)


def test_valid_bound_approval_allows_threshold_checkout(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    mandate_factory: Callable[..., Any],
    approval_factory: Callable[..., Any],
    now: datetime,
) -> None:
    raw = request_factory(approval_id="approval-1")
    approval = bound_approval(approval_factory)
    decision = PolicyEngine().evaluate(
        raw,
        state_factory(
            mandate=mandate_factory(approval_threshold_paise=10_000),
            approvals=(approval,),
        ),
        evaluated_at=now,
    )
    assert decision.outcome is DecisionOutcome.ALLOW


def test_invalid_supplied_approval_blocks_even_below_threshold(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    now: datetime,
) -> None:
    decision = PolicyEngine().evaluate(
        request_factory(approval_id="missing"), state_factory(), evaluated_at=now
    )
    assert decision.rule_id is RuleId.APPROVAL
