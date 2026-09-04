"""Pure deterministic decisions for requests that have no resolvable mandate state."""

from collections.abc import Mapping
from datetime import datetime

from mandateguard.domain.enums import (
    DecisionOutcome,
    EvidenceStatus,
    ExecutionMode,
    RuleId,
)
from mandateguard.domain.models import GuardDecision, RuleEvidence, SafeRequestEnvelope, ToolRequest
from mandateguard.domain.validation import normalize_utc
from mandateguard.policy.canonical import (
    semantic_evidence_projection,
    semantic_request_projection,
    sha256_value,
)
from mandateguard.policy.engine import POLICY_VERSION
from mandateguard.policy.rules import evidence


def _not_applicable(rule_id: RuleId, reason: str) -> RuleEvidence:
    return evidence(rule_id, EvidenceStatus.NOT_APPLICABLE, reason)


def _decision(
    *,
    request: ToolRequest | None,
    envelope: SafeRequestEnvelope,
    evaluated_at: datetime,
    decisive_rule: RuleId,
    reason: str,
    evidence_items: tuple[RuleEvidence, ...],
    relevant_state: Mapping[str, object],
) -> GuardDecision:
    timestamp = normalize_utc(evaluated_at)
    fingerprint = sha256_value(
        {
            "policy_version": POLICY_VERSION,
            "request": (
                semantic_request_projection(request)
                if request is not None
                else envelope.semantic_sha256
            ),
            "relevant_state": relevant_state,
            "evaluated_at": timestamp,
            "outcome": DecisionOutcome.BLOCK,
            "decisive_rule": decisive_rule,
            "reason": reason,
            "evidence": tuple(semantic_evidence_projection(item) for item in evidence_items),
        }
    )
    return GuardDecision(
        outcome=DecisionOutcome.BLOCK,
        rule_id=decisive_rule,
        reason=reason,
        evidence=evidence_items,
        execution_mode=ExecutionMode.NONE,
        policy_version=POLICY_VERSION,
        evaluated_at=timestamp,
        request=envelope,
        fingerprint=fingerprint,
    )


def malformed_request_decision(
    *,
    envelope: SafeRequestEnvelope,
    evaluated_at: datetime,
    error_locations: tuple[str, ...],
) -> GuardDecision:
    """Return state-free MG-001 for a malformed request."""

    evidence_items = (
        evidence(
            RuleId.REQUEST_CONTRACT,
            EvidenceStatus.FAIL,
            "request_contract_invalid",
            {"error_count": len(error_locations), "error_locations": error_locations},
        ),
        *(_not_applicable(rule_id, "request_contract_invalid") for rule_id in tuple(RuleId)[1:]),
    )
    return _decision(
        request=None,
        envelope=envelope,
        evaluated_at=evaluated_at,
        decisive_rule=RuleId.REQUEST_CONTRACT,
        reason="request_contract_invalid",
        evidence_items=evidence_items,
        relevant_state={"mandate": "unavailable"},
    )


def unknown_mandate_decision(
    *, request: ToolRequest, envelope: SafeRequestEnvelope, evaluated_at: datetime
) -> GuardDecision:
    """Return state-free MG-003 for a valid request with no mandate."""

    evidence_items = tuple(
        evidence(rule_id, EvidenceStatus.PASS, "request_contract_valid")
        if rule_id is RuleId.REQUEST_CONTRACT
        else evidence(rule_id, EvidenceStatus.FAIL, "mandate_not_found")
        if rule_id is RuleId.MANDATE_STATUS
        else _not_applicable(rule_id, "mandate_state_unavailable")
        for rule_id in RuleId
    )
    return _decision(
        request=request,
        envelope=envelope,
        evaluated_at=evaluated_at,
        decisive_rule=RuleId.MANDATE_STATUS,
        reason="mandate_not_found",
        evidence_items=evidence_items,
        relevant_state={"mandate": "not_found"},
    )
