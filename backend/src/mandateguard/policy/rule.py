from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from mandateguard.domain.enums import DecisionOutcome, ExecutionMode, RuleId
from mandateguard.domain.models import Product, RuleEvidence, ToolRequest
from mandateguard.domain.state import EvaluationState


@dataclass(frozen=True, slots=True)
class RuleContext:
    request: ToolRequest
    state: EvaluationState
    evaluated_at: datetime
    request_hash: str | None
    total_paise: int | None
    product: Product | None


@dataclass(frozen=True, slots=True)
class RuleResult:
    evidence: RuleEvidence
    outcome: DecisionOutcome | None = None
    execution_mode: ExecutionMode = ExecutionMode.NONE


class PolicyRule(Protocol):
    rule_id: RuleId

    def evaluate(self, context: RuleContext) -> RuleResult: ...
