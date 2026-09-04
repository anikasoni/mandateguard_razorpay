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


def test_malformed_decision_matches_frozen_phase2a_vector(
    state_factory: Callable[..., EvaluationState], now: datetime
) -> None:
    """Freeze the checked-in Phase 2A malformed-request contract across Phase 2B."""

    raw = {
        "request_id": "request-1",
        "mandate_id": "mandate-1",
        "tool": "create_checkout",
        "arguments": {
            "product_id": "product-1",
            "checkout_intent_id": "intent-1",
            "quantity": "2",
            "currency": "INR",
            "quoted_unit_price_paise": 5_000,
            "price_version": 7,
            "inventory_version": 4,
            "approval_id": None,
        },
    }
    decision = PolicyEngine().evaluate(raw, state_factory(), evaluated_at=now)

    assert decision.request.model_dump(mode="json") == {
        "request_id": "request-1",
        "mandate_id": "mandate-1",
        "tool": "create_checkout",
        "field_names": ["arguments", "mandate_id", "request_id", "tool"],
        "argument_field_names": [
            "approval_id",
            "checkout_intent_id",
            "currency",
            "inventory_version",
            "price_version",
            "product_id",
            "quantity",
            "quoted_unit_price_paise",
        ],
        "raw_sha256": "e7d6c21448a0e6fdc52fc56370960c3e0034b1b413816a32448ac74913307a45",
        "semantic_sha256": "cde627fb93815ffd8b9dde8ebc656319fe19b0e8a6cf51890b0afb5f2ba18836",
    }
    assert [item.model_dump(mode="json") for item in decision.evidence] == [
        {
            "rule_id": "MG-001",
            "status": "fail",
            "reason": "request_contract_invalid",
            "facts": [
                {"key": "error_count", "value": 1},
                {
                    "key": "error_locations",
                    "value": ["create_checkout.arguments.quantity"],
                },
            ],
        },
        {
            "rule_id": "MG-002",
            "status": "not_applicable",
            "reason": "request_contract_invalid",
            "facts": [],
        },
        {
            "rule_id": "MG-003",
            "status": "not_applicable",
            "reason": "request_contract_invalid",
            "facts": [],
        },
        {
            "rule_id": "MG-004",
            "status": "not_applicable",
            "reason": "request_contract_invalid",
            "facts": [],
        },
        {
            "rule_id": "MG-005",
            "status": "not_applicable",
            "reason": "request_contract_invalid",
            "facts": [],
        },
        {
            "rule_id": "MG-006",
            "status": "not_applicable",
            "reason": "request_contract_invalid",
            "facts": [],
        },
        {
            "rule_id": "MG-007",
            "status": "not_applicable",
            "reason": "request_contract_invalid",
            "facts": [],
        },
        {
            "rule_id": "MG-008",
            "status": "not_applicable",
            "reason": "request_contract_invalid",
            "facts": [],
        },
        {
            "rule_id": "MG-009",
            "status": "not_applicable",
            "reason": "request_contract_invalid",
            "facts": [],
        },
        {
            "rule_id": "MG-010",
            "status": "not_applicable",
            "reason": "request_contract_invalid",
            "facts": [],
        },
        {
            "rule_id": "MG-011",
            "status": "not_applicable",
            "reason": "request_contract_invalid",
            "facts": [],
        },
    ]
    assert decision.fingerprint == (
        "6e82feba81bbf58b9e0e9fcd85b8f6f3157347a6ba6b9db7fa883cb516a7bd0e"
    )


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
