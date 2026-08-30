from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mandateguard.domain.enums import (
    ApprovalStatus,
    CheckoutStatus,
    DecisionOutcome,
    EvidenceStatus,
    ExecutionMode,
    MandateStatus,
    RuleId,
    ToolName,
)
from mandateguard.domain.validation import (
    CanonicalId,
    CurrencyCode,
    Identifier,
    NonNegativeInteger,
    Paise,
    PositiveQuantity,
    UtcDateTime,
)


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Mandate(FrozenModel):
    mandate_id: Identifier
    status: MandateStatus
    currency: CurrencyCode
    total_budget_paise: Paise
    per_item_cap_paise: Paise
    approval_threshold_paise: Paise
    approved_merchants: frozenset[CanonicalId]
    approved_categories: frozenset[CanonicalId]
    expires_at: UtcDateTime

    @model_validator(mode="after")
    def validate_limits_and_scope(self) -> "Mandate":
        if self.per_item_cap_paise > self.total_budget_paise:
            raise ValueError("per-item cap cannot exceed total budget")
        if self.approval_threshold_paise > self.total_budget_paise:
            raise ValueError("approval threshold cannot exceed total budget")
        if not self.approved_merchants or not self.approved_categories:
            raise ValueError("merchant and category allowlists cannot be empty")
        return self


class Product(FrozenModel):
    product_id: Identifier
    merchant_id: CanonicalId
    category_id: CanonicalId
    currency: CurrencyCode
    unit_price_paise: Paise
    inventory_count: NonNegativeInteger
    price_version: NonNegativeInteger
    inventory_version: NonNegativeInteger
    active: bool
    offer_expires_at: UtcDateTime | None = None


class Approval(FrozenModel):
    approval_id: Identifier
    mandate_id: Identifier
    checkout_intent_id: Identifier
    request_hash: Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
    amount_paise: Paise
    currency: CurrencyCode
    status: ApprovalStatus
    expires_at: UtcDateTime

    def is_live_at(self, evaluated_at: datetime) -> bool:
        return self.expires_at > evaluated_at


class CheckoutAttempt(FrozenModel):
    attempt_id: Identifier
    idempotency_key: Identifier
    mandate_id: Identifier
    checkout_intent_id: Identifier
    request_hash: Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
    product_id: Identifier
    quantity: PositiveQuantity
    amount_paise: Paise
    currency: CurrencyCode
    status: CheckoutStatus
    reservation_expires_at: UtcDateTime | None = None
    approval_id: Identifier | None = None

    @model_validator(mode="after")
    def validate_reservation(self) -> "CheckoutAttempt":
        needs_expiry = self.status in {CheckoutStatus.RESERVED, CheckoutStatus.CREATED}
        permits_expiry = needs_expiry or self.status is CheckoutStatus.RETRYABLE_FAILED
        if needs_expiry and self.reservation_expires_at is None:
            raise ValueError("reserved and created attempts require a reservation expiry")
        if not permits_expiry and self.reservation_expires_at is not None:
            raise ValueError("this checkout status cannot retain a reservation expiry")
        return self

    def contributes_spend_at(self, evaluated_at: datetime) -> bool:
        if self.status is CheckoutStatus.COMPLETED:
            return True
        return (
            self.status
            in {
                CheckoutStatus.RESERVED,
                CheckoutStatus.CREATED,
                CheckoutStatus.RETRYABLE_FAILED,
            }
            and self.reservation_expires_at is not None
            and self.reservation_expires_at > evaluated_at
        )

    def is_replayable_at(self, evaluated_at: datetime) -> bool:
        del evaluated_at
        return self.status in {
            CheckoutStatus.RESERVED,
            CheckoutStatus.CREATED,
            CheckoutStatus.COMPLETED,
        }

    @property
    def retryable(self) -> bool:
        return self.status is CheckoutStatus.RETRYABLE_FAILED


class OfferClaims(FrozenModel):
    claimed_inventory_count: NonNegativeInteger | None = None
    claimed_offer_expires_at: UtcDateTime | None = None
    claimed_unit_price_paise: Paise | None = None


class GetProductArguments(FrozenModel):
    product_id: Identifier
    currency: CurrencyCode


class PresentOfferArguments(FrozenModel):
    product_id: Identifier
    checkout_intent_id: Identifier
    quantity: PositiveQuantity
    currency: CurrencyCode
    quoted_unit_price_paise: Paise
    price_version: NonNegativeInteger
    inventory_version: NonNegativeInteger
    claims: OfferClaims = Field(default_factory=OfferClaims)


class FinancialIntentArguments(FrozenModel):
    product_id: Identifier
    checkout_intent_id: Identifier
    quantity: PositiveQuantity
    currency: CurrencyCode
    quoted_unit_price_paise: Paise
    price_version: NonNegativeInteger
    inventory_version: NonNegativeInteger
    approval_id: Identifier | None = None


class RequestBase(FrozenModel):
    request_id: Identifier
    mandate_id: Identifier


class GetProductRequest(RequestBase):
    tool: Literal[ToolName.GET_PRODUCT]
    arguments: GetProductArguments


class PresentOfferRequest(RequestBase):
    tool: Literal[ToolName.PRESENT_OFFER]
    arguments: PresentOfferArguments


class RequestApprovalRequest(RequestBase):
    tool: Literal[ToolName.REQUEST_APPROVAL]
    arguments: FinancialIntentArguments


class CreateCheckoutRequest(RequestBase):
    tool: Literal[ToolName.CREATE_CHECKOUT]
    arguments: FinancialIntentArguments


type ToolRequest = Annotated[
    GetProductRequest | PresentOfferRequest | RequestApprovalRequest | CreateCheckoutRequest,
    Field(discriminator="tool"),
]


type EvidenceScalar = str | int | bool | None


class EvidenceFact(FrozenModel):
    key: Annotated[str, Field(strict=True, pattern=r"^[a-z][a-z0-9_]*$")]
    value: EvidenceScalar | tuple[EvidenceScalar, ...]


class RuleEvidence(FrozenModel):
    rule_id: RuleId
    status: EvidenceStatus
    reason: Annotated[str, Field(strict=True, min_length=1)]
    facts: tuple[EvidenceFact, ...] = ()


class SafeRequestEnvelope(FrozenModel):
    request_id: str | None
    mandate_id: str | None
    tool: str | None
    field_names: tuple[str, ...]
    argument_field_names: tuple[str, ...]
    raw_sha256: Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
    semantic_sha256: Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]


class GuardDecision(FrozenModel):
    outcome: DecisionOutcome
    rule_id: RuleId
    reason: Annotated[str, Field(strict=True, min_length=1)]
    evidence: Annotated[tuple[RuleEvidence, ...], Field(min_length=11, max_length=11)]
    execution_mode: ExecutionMode
    policy_version: Literal["2026-08-30.phase2a"]
    evaluated_at: UtcDateTime
    request: SafeRequestEnvelope
    fingerprint: Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
