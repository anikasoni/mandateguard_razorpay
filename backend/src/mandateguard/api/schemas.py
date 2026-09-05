"""HTTP-only request, response, and error contracts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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


class CreatePaymentOrderRequest(ApiModel):
    attempt_id: Identifier


class PaymentOrderResponse(ApiModel):
    provider_order_id: Identifier
    attempt_id: Identifier
    amount_paise: int
    currency: Literal["INR"]
    status: Literal["created", "paid"]
    provider_mode: Literal["razorpay_test", "simulated"]
    checkout_key_id: str | None
    replayed: bool


class VerifyPaymentRequest(ApiModel):
    provider_order_id: Identifier
    provider_payment_id: Identifier
    signature: str = Field(pattern=r"^[0-9a-f]{64}$")


class PaymentVerificationResponse(ApiModel):
    provider_order_id: Identifier
    provider_payment_id: Identifier
    attempt_id: Identifier
    status: Literal["paid"]
    replayed: bool


class AgentRunRequest(ApiModel):
    mandate_id: Identifier
    user_request: str = Field(min_length=3, max_length=500)


class AgentPlanResponse(ApiModel):
    product_id: Identifier
    quantity: int
    claimed_inventory_count: int | None
    rationale: str
    provider: Literal["gemini", "offline_demo"]


class AgentStepResponse(ApiModel):
    audit_event_id: Identifier
    decision: GuardDecision
    approval: Approval | None
    checkout_attempt: CheckoutAttempt | None


class AgentRunResponse(ApiModel):
    run_id: Identifier
    checkout_intent_id: Identifier
    plan: AgentPlanResponse
    status: Literal["blocked", "checkout_reserved", "awaiting_human_approval"]
    steps: tuple[AgentStepResponse, ...]
    external_execution_authorized: Literal[False] = False
