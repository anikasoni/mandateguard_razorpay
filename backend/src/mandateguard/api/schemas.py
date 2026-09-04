"""HTTP-only request, response, and error contracts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from mandateguard.domain.models import Approval, CheckoutAttempt, GuardDecision
from mandateguard.domain.validation import Identifier


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorDetail(ApiModel):
    code: str
    message: str
    retryable: bool
    fields: tuple[str, ...] | None = None


class ErrorResponse(ApiModel):
    error: ErrorDetail


class PolicyEvaluationResponse(ApiModel):
    audit_event_id: str
    decision: GuardDecision
    approval: Approval | None
    checkout_attempt: CheckoutAttempt | None
    external_execution_authorized: Literal[False] = False


class HumanApprovalDecisionRequest(ApiModel):
    checkout_intent_id: Identifier
    decision: Literal["grant", "reject"]


class HumanApprovalDecisionResponse(ApiModel):
    approval: Approval
    decision: Literal["grant", "reject"]
    evaluated_at: datetime
    replayed: bool
    audit_event_id: str
