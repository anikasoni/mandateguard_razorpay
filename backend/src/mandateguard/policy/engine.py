from datetime import datetime
from typing import Any, Literal

from pydantic import TypeAdapter, ValidationError

from mandateguard.domain.enums import (
    DecisionOutcome,
    EvidenceStatus,
    ExecutionMode,
    RuleId,
    ToolName,
)
from mandateguard.domain.models import GuardDecision, RuleEvidence, ToolRequest
from mandateguard.domain.state import EvaluationState
from mandateguard.domain.validation import (
    IntegerOverflowError,
    checked_multiply,
    normalize_utc,
)
from mandateguard.policy.canonical import (
    intent_arguments,
    intent_hash,
    safe_request_envelope,
    semantic_approval_projection,
    semantic_attempt_projection,
    semantic_evidence_projection,
    semantic_mandate_projection,
    semantic_product_projection,
    semantic_request_projection,
    semantic_sorted,
    sha256_value,
)
from mandateguard.policy.registry import APPLICABLE_RULES, RULE_REGISTRY
from mandateguard.policy.rule import RuleContext, RuleResult
from mandateguard.policy.rules import evidence, not_applicable

POLICY_VERSION: Literal["2026-08-30.phase2a"] = "2026-08-30.phase2a"
_REQUEST_ADAPTER: TypeAdapter[ToolRequest] = TypeAdapter(ToolRequest)


class PolicyEngine:
    def evaluate(
        self, raw_request: object, state: EvaluationState, *, evaluated_at: datetime
    ) -> GuardDecision:
        timestamp = normalize_utc(evaluated_at)
        envelope = safe_request_envelope(raw_request)
        try:
            request = _REQUEST_ADAPTER.validate_python(raw_request)
        except ValidationError as error:
            locations = tuple(
                sorted(".".join(str(part) for part in item["loc"]) for item in error.errors())
            )
            return self._contract_block(
                envelope,
                state,
                timestamp,
                "request_contract_invalid",
                {"error_count": len(locations), "error_locations": locations},
            )

        if request.mandate_id != state.mandate.mandate_id:
            return self._contract_block(
                envelope,
                state,
                timestamp,
                "mandate_identity_mismatch",
                {
                    "request_mandate_id": request.mandate_id,
                    "state_mandate_id": state.mandate.mandate_id,
                },
            )

        arguments = intent_arguments(request)
        try:
            total = (
                checked_multiply(arguments.quoted_unit_price_paise, arguments.quantity)
                if arguments is not None
                else None
            )
        except IntegerOverflowError:
            return self._contract_block(
                envelope, state, timestamp, "transaction_total_overflow", {}
            )

        context = RuleContext(
            request=request,
            state=state,
            evaluated_at=timestamp,
            request_hash=intent_hash(request),
            total_paise=total,
            product=state.product(request.arguments.product_id),
        )
        results = self._evaluate_registry(context)
        decisive = next((item for item in results if item.outcome is not None), None)
        if decisive is None:
            applicable = APPLICABLE_RULES[request.tool]
            decisive_rule = next(
                rule.rule_id for rule in reversed(RULE_REGISTRY) if rule.rule_id in applicable
            )
            outcome = DecisionOutcome.ALLOW
            reason = "all_applicable_rules_passed"
            execution_mode = ExecutionMode.EXECUTE
        else:
            decisive_rule = decisive.evidence.rule_id
            assert decisive.outcome is not None
            outcome = decisive.outcome
            reason = decisive.evidence.reason
            execution_mode = decisive.execution_mode
            retry_requested = any(
                item.execution_mode is ExecutionMode.RETRY_EXISTING for item in results
            )
            if (
                retry_requested
                and outcome is DecisionOutcome.ALLOW
                and decisive_rule is RuleId.AUTHORIZATION
                and request.tool is ToolName.CREATE_CHECKOUT
            ):
                execution_mode = ExecutionMode.RETRY_EXISTING

        return self._decision(
            outcome=outcome,
            decisive_rule=decisive_rule,
            reason=reason,
            results=results,
            execution_mode=execution_mode,
            evaluated_at=timestamp,
            envelope=envelope,
            state=state,
            request=request,
        )

    @staticmethod
    def _evaluate_registry(context: RuleContext) -> tuple[RuleResult, ...]:
        applicable = APPLICABLE_RULES[context.request.tool]
        return tuple(
            rule.evaluate(context) if rule.rule_id in applicable else not_applicable(rule.rule_id)
            for rule in RULE_REGISTRY
        )

    def _contract_block(
        self,
        envelope: Any,
        state: EvaluationState,
        evaluated_at: datetime,
        reason: str,
        facts: dict[str, Any],
    ) -> GuardDecision:
        results = (
            RuleResult(evidence(RuleId.REQUEST_CONTRACT, EvidenceStatus.FAIL, reason, facts)),
            *(
                not_applicable(rule.rule_id, "request_contract_invalid")
                for rule in RULE_REGISTRY[1:]
            ),
        )
        return self._decision(
            outcome=DecisionOutcome.BLOCK,
            decisive_rule=RuleId.REQUEST_CONTRACT,
            reason=reason,
            results=results,
            execution_mode=ExecutionMode.NONE,
            evaluated_at=evaluated_at,
            envelope=envelope,
            state=state,
            request=None,
        )

    @staticmethod
    def _relevant_state(state: EvaluationState, request: ToolRequest | None) -> dict[str, Any]:
        if request is None:
            return {"mandate": semantic_mandate_projection(state.mandate)}
        arguments = intent_arguments(request)
        product = state.product(request.arguments.product_id)
        snapshot: dict[str, Any] = {
            "mandate": semantic_mandate_projection(state.mandate),
            "product": semantic_product_projection(product),
        }
        if arguments is not None and request.tool in {
            ToolName.REQUEST_APPROVAL,
            ToolName.CREATE_CHECKOUT,
        }:
            snapshot["approvals"] = semantic_sorted(
                tuple(
                    semantic_approval_projection(item)
                    for item in state.approvals_for(
                        request.mandate_id, arguments.checkout_intent_id
                    )
                )
            )
            snapshot["attempts"] = semantic_sorted(
                tuple(
                    semantic_attempt_projection(item)
                    for item in state.attempts_for(request.mandate_id, arguments.checkout_intent_id)
                )
            )
            snapshot["spend_attempts"] = semantic_sorted(
                tuple(
                    semantic_attempt_projection(item)
                    for item in state.checkout_attempts
                    if item.mandate_id == request.mandate_id
                )
            )
        elif arguments is not None:
            snapshot["spend_attempts"] = semantic_sorted(
                tuple(
                    semantic_attempt_projection(item)
                    for item in state.checkout_attempts
                    if item.mandate_id == request.mandate_id
                )
            )
        return snapshot

    def _decision(
        self,
        *,
        outcome: DecisionOutcome,
        decisive_rule: RuleId,
        reason: str,
        results: tuple[RuleResult, ...],
        execution_mode: ExecutionMode,
        evaluated_at: datetime,
        envelope: Any,
        state: EvaluationState,
        request: ToolRequest | None,
    ) -> GuardDecision:
        evidence_items: tuple[RuleEvidence, ...] = tuple(item.evidence for item in results)
        fingerprint = sha256_value(
            {
                "policy_version": POLICY_VERSION,
                "request": (
                    semantic_request_projection(request)
                    if request is not None
                    else envelope.semantic_sha256
                ),
                "relevant_state": self._relevant_state(state, request),
                "evaluated_at": evaluated_at,
                "outcome": outcome,
                "decisive_rule": decisive_rule,
                "reason": reason,
                "evidence": tuple(semantic_evidence_projection(item) for item in evidence_items),
            }
        )
        return GuardDecision(
            outcome=outcome,
            rule_id=decisive_rule,
            reason=reason,
            evidence=evidence_items,
            execution_mode=execution_mode,
            policy_version=POLICY_VERSION,
            evaluated_at=evaluated_at,
            request=envelope,
            fingerprint=fingerprint,
        )
