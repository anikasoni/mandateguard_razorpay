from collections.abc import Callable
from datetime import datetime
from typing import Any

import pytest

from mandateguard.domain import DecisionOutcome, EvaluationState, EvidenceStatus, RuleId, ToolName
from mandateguard.policy import APPLICABLE_RULES, RULE_REGISTRY, PolicyEngine


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        (lambda raw: {**raw, "tool": "unknown_tool"}, "request_contract_invalid"),
        (lambda raw: {**raw, "unknown": True}, "request_contract_invalid"),
        (
            lambda raw: {
                **raw,
                "arguments": {**raw["arguments"], "quoted_unit_price_paise": True},
            },
            "request_contract_invalid",
        ),
        (
            lambda raw: {**raw, "arguments": {**raw["arguments"], "quantity": 1.5}},
            "request_contract_invalid",
        ),
    ],
)
def test_untrusted_contract_failures_are_mg001_decisions(
    mutation: Callable[[dict[str, Any]], dict[str, Any]],
    expected_reason: str,
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    now: datetime,
) -> None:
    decision = PolicyEngine().evaluate(
        mutation(request_factory()), state_factory(), evaluated_at=now
    )
    assert (decision.outcome, decision.rule_id, decision.reason) == (
        DecisionOutcome.BLOCK,
        RuleId.REQUEST_CONTRACT,
        expected_reason,
    )
    assert decision.request.raw_sha256


def test_mandate_identity_mismatch_is_mg001(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    now: datetime,
) -> None:
    raw = request_factory()
    raw["mandate_id"] = "different-mandate"
    decision = PolicyEngine().evaluate(raw, state_factory(), evaluated_at=now)
    assert decision.rule_id is RuleId.REQUEST_CONTRACT
    assert decision.reason == "mandate_identity_mismatch"


def test_registry_is_complete_and_ordered() -> None:
    assert tuple(rule.rule_id for rule in RULE_REGISTRY) == tuple(RuleId)


@pytest.mark.parametrize(
    "tool", ["get_product", "present_offer", "request_approval", "create_checkout"]
)
def test_applicability_emits_evidence_for_all_rules(
    tool: str,
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    now: datetime,
) -> None:
    decision = PolicyEngine().evaluate(request_factory(tool), state_factory(), evaluated_at=now)
    assert tuple(item.rule_id for item in decision.evidence) == tuple(RuleId)
    applicable = APPLICABLE_RULES[ToolName(tool)]
    assert {
        item.rule_id
        for item in decision.evidence
        if item.status is not EvidenceStatus.NOT_APPLICABLE
    } == applicable


def test_get_product_does_not_inspect_financial_state(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    approval_factory: Callable[..., Any],
    attempt_factory: Callable[..., Any],
    now: datetime,
) -> None:
    state = state_factory(
        approvals=(approval_factory(status="revoked"),),
        checkout_attempts=(attempt_factory(amount_paise=99_999),),
    )
    decision = PolicyEngine().evaluate(request_factory("get_product"), state, evaluated_at=now)
    assert decision.outcome is DecisionOutcome.ALLOW
    assert decision.rule_id is RuleId.SCOPE
