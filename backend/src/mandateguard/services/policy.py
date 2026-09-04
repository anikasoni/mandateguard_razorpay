"""Transactional persistence orchestration around the pure Phase 2A policy engine."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from mandateguard.core.config import Settings
from mandateguard.db.repositories import (
    ApprovalRepository,
    AuditRepository,
    CheckoutAttemptRepository,
    EvaluationStateRepository,
    MandateRepository,
)
from mandateguard.db.session import SessionFactory, immediate_policy_session
from mandateguard.domain.enums import (
    ApprovalStatus,
    CheckoutStatus,
    DecisionOutcome,
    ExecutionMode,
    ToolName,
)
from mandateguard.domain.models import (
    Approval,
    CheckoutAttempt,
    FinancialIntentArguments,
    GuardDecision,
    ToolRequest,
)
from mandateguard.domain.state import EvaluationState
from mandateguard.domain.validation import checked_multiply, normalize_utc
from mandateguard.policy import PolicyEngine
from mandateguard.policy.canonical import (
    intent_hash,
    safe_request_envelope,
    sha256_value,
)
from mandateguard.policy.state_free import (
    malformed_request_decision,
    unknown_mandate_decision,
)
from mandateguard.services.request_projection import (
    safe_audit_arguments,
    safe_persistence_request_envelope,
    safe_validation_error_locations,
)

_REQUEST_ADAPTER: TypeAdapter[ToolRequest] = TypeAdapter(ToolRequest)
type IdFactory = Callable[[str], str]
type AuditRepositoryFactory = Callable[[Session], AuditRepository]


class InvalidEffectExpirationError(RuntimeError):
    """Raised when trusted TTLs cannot produce a live persisted effect."""


@dataclass(frozen=True, slots=True)
class PolicyServiceResult:
    """Committed policy result; it never grants permission for external execution.

    In particular, ``execution_mode=REPLAY`` means only that the existing record is returned.
    Phase 2B has no checkout executor.
    """

    decision: GuardDecision
    approval: Approval | None
    checkout_attempt: CheckoutAttempt | None
    audit_event_id: str


@dataclass(frozen=True, slots=True)
class _Effect:
    approval: Approval | None = None
    checkout_attempt: CheckoutAttempt | None = None


def _default_id_factory(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


class PolicyService:
    """Evaluate, persist effects, and audit using one owned SQLite transaction."""

    def __init__(
        self,
        session_factory: SessionFactory,
        settings: Settings,
        *,
        engine: PolicyEngine | None = None,
        id_factory: IdFactory = _default_id_factory,
        audit_repository_factory: AuditRepositoryFactory = AuditRepository,
    ) -> None:
        self._session_factory = session_factory
        self._approval_ttl = timedelta(seconds=settings.pending_approval_ttl_seconds)
        self._reservation_ttl = timedelta(seconds=settings.checkout_reservation_ttl_seconds)
        self._engine = engine or PolicyEngine()
        self._id_factory = id_factory
        self._audit_repository_factory = audit_repository_factory

    def evaluate(self, raw_request: object, *, evaluated_at: datetime) -> PolicyServiceResult:
        timestamp = normalize_utc(evaluated_at)
        provisional: PolicyServiceResult | None = None

        with immediate_policy_session(self._session_factory) as session:
            decision, request, state = self._evaluate_in_transaction(
                session, raw_request, timestamp
            )
            effect = self._apply_effect(session, decision, request, state, timestamp)
            session.flush()

            envelope = decision.request
            arguments = safe_audit_arguments(raw_request, request, envelope)
            audit_event_id = self._id_factory("audit")
            self._audit_repository_factory(session).append(
                event_id=audit_event_id,
                decision=decision,
                arguments=arguments,
                effect_approval_id=(
                    effect.approval.approval_id if effect.approval is not None else None
                ),
                effect_attempt_id=(
                    effect.checkout_attempt.attempt_id
                    if effect.checkout_attempt is not None
                    else None
                ),
            )
            session.flush()
            provisional = PolicyServiceResult(
                decision=decision,
                approval=effect.approval,
                checkout_attempt=effect.checkout_attempt,
                audit_event_id=audit_event_id,
            )

        if provisional is None:
            raise RuntimeError("policy transaction committed without a result")
        return provisional

    def _evaluate_in_transaction(
        self, session: Session, raw_request: object, evaluated_at: datetime
    ) -> tuple[GuardDecision, ToolRequest | None, EvaluationState | None]:
        try:
            request = _REQUEST_ADAPTER.validate_python(raw_request)
        except ValidationError as error:
            envelope = safe_persistence_request_envelope(raw_request)
            return (
                malformed_request_decision(
                    envelope=envelope,
                    evaluated_at=evaluated_at,
                    error_locations=safe_validation_error_locations(error),
                ),
                None,
                None,
            )

        envelope = safe_request_envelope(raw_request)

        mandate_repository = MandateRepository(session)
        mandate = mandate_repository.get(request.mandate_id)
        if mandate is None:
            return (
                unknown_mandate_decision(
                    request=request, envelope=envelope, evaluated_at=evaluated_at
                ),
                request,
                None,
            )

        ApprovalRepository(session).release_expired_live_bindings(request.mandate_id, evaluated_at)
        state = EvaluationStateRepository(session).load(
            request.mandate_id, product_id=request.arguments.product_id
        )
        if state is None:
            raise RuntimeError("mandate disappeared while holding the SQLite write lock")
        return self._engine.evaluate(raw_request, state, evaluated_at=evaluated_at), request, state

    def _apply_effect(
        self,
        session: Session,
        decision: GuardDecision,
        request: ToolRequest | None,
        state: EvaluationState | None,
        evaluated_at: datetime,
    ) -> _Effect:
        if request is None or state is None or decision.outcome is not DecisionOutcome.ALLOW:
            return _Effect()
        if request.tool is ToolName.REQUEST_APPROVAL:
            return self._apply_approval_effect(session, decision, request, state, evaluated_at)
        if request.tool is ToolName.CREATE_CHECKOUT:
            return self._apply_checkout_effect(session, decision, request, state, evaluated_at)
        return _Effect()

    def _apply_approval_effect(
        self,
        session: Session,
        decision: GuardDecision,
        request: ToolRequest,
        state: EvaluationState,
        evaluated_at: datetime,
    ) -> _Effect:
        arguments = request.arguments
        if not isinstance(arguments, FinancialIntentArguments):
            return _Effect()
        request_hash = intent_hash(request)
        if request_hash is None:
            raise RuntimeError("approval request did not produce an intent hash")
        amount = checked_multiply(arguments.quoted_unit_price_paise, arguments.quantity)

        matching = next(
            (
                item
                for item in state.approvals_for(request.mandate_id, arguments.checkout_intent_id)
                if item.status in {ApprovalStatus.PENDING, ApprovalStatus.GRANTED}
                and item.is_live_at(evaluated_at)
                and item.request_hash == request_hash
                and item.amount_paise == amount
                and item.currency == arguments.currency
            ),
            None,
        )
        if decision.execution_mode is ExecutionMode.REPLAY:
            if matching is None:
                raise RuntimeError("approval replay has no matching stored approval")
            return _Effect(approval=matching)
        if decision.execution_mode is not ExecutionMode.EXECUTE:
            return _Effect()

        expires_at = self._effect_expiry(evaluated_at, self._approval_ttl, state.mandate.expires_at)
        approval = Approval(
            approval_id=self._id_factory("approval"),
            mandate_id=request.mandate_id,
            checkout_intent_id=arguments.checkout_intent_id,
            request_hash=request_hash,
            amount_paise=amount,
            currency=arguments.currency,
            status=ApprovalStatus.PENDING,
            expires_at=expires_at,
        )
        ApprovalRepository(session).add(approval, evaluated_at=evaluated_at)
        return _Effect(approval=approval)

    def _apply_checkout_effect(
        self,
        session: Session,
        decision: GuardDecision,
        request: ToolRequest,
        state: EvaluationState,
        evaluated_at: datetime,
    ) -> _Effect:
        arguments = request.arguments
        if not isinstance(arguments, FinancialIntentArguments):
            return _Effect()
        request_hash = intent_hash(request)
        if request_hash is None:
            raise RuntimeError("checkout request did not produce an intent hash")
        amount = checked_multiply(arguments.quoted_unit_price_paise, arguments.quantity)
        matching = self._matching_attempt(state, request, request_hash, amount)

        if decision.execution_mode is ExecutionMode.REPLAY:
            if matching is None:
                raise RuntimeError("checkout replay has no matching stored attempt")
            approval = self._approval_by_id(state, matching.approval_id)
            return _Effect(approval=approval, checkout_attempt=matching)

        approvals = ApprovalRepository(session)
        consumed_or_bound: Approval | None = None
        if arguments.approval_id is not None:
            current = self._approval_by_id(state, arguments.approval_id)
            if current is not None and current.status is ApprovalStatus.CONSUMED:
                consumed_or_bound = current
            else:
                consumed_or_bound = approvals.consume_granted(arguments.approval_id)

        attempts = CheckoutAttemptRepository(session)
        if decision.execution_mode is ExecutionMode.RETRY_EXISTING:
            if matching is None or not matching.retryable:
                raise RuntimeError("retry decision has no retryable stored attempt")
            bound_approval = consumed_or_bound or self._approval_by_id(state, matching.approval_id)
            needs_renewal = not matching.contributes_spend_at(evaluated_at)
            needs_rebind = (
                consumed_or_bound is not None
                and consumed_or_bound.approval_id != matching.approval_id
            )
            if not needs_renewal and not needs_rebind:
                return _Effect(approval=bound_approval, checkout_attempt=matching)
            expiry = (
                self._effect_expiry(evaluated_at, self._reservation_ttl, state.mandate.expires_at)
                if needs_renewal
                else matching.reservation_expires_at
            )
            if expiry is None:
                raise InvalidEffectExpirationError("retry renewal requires an expiry")
            renewed = attempts.renew_retry_reservation(
                matching.attempt_id,
                reservation_expires_at=expiry,
                approval_id=(
                    consumed_or_bound.approval_id
                    if consumed_or_bound is not None
                    else matching.approval_id
                ),
            )
            return _Effect(approval=bound_approval, checkout_attempt=renewed)

        if decision.execution_mode is not ExecutionMode.EXECUTE:
            return _Effect()
        expiry = self._effect_expiry(evaluated_at, self._reservation_ttl, state.mandate.expires_at)
        attempt = CheckoutAttempt(
            attempt_id=self._id_factory("attempt"),
            idempotency_key=sha256_value(
                {
                    "mandate_id": request.mandate_id,
                    "product_id": arguments.product_id,
                    "request_hash": request_hash,
                }
            ),
            mandate_id=request.mandate_id,
            checkout_intent_id=arguments.checkout_intent_id,
            request_hash=request_hash,
            product_id=arguments.product_id,
            quantity=arguments.quantity,
            amount_paise=amount,
            currency=arguments.currency,
            status=CheckoutStatus.RESERVED,
            reservation_expires_at=expiry,
            approval_id=(consumed_or_bound.approval_id if consumed_or_bound is not None else None),
        )
        attempts.add(attempt)
        return _Effect(approval=consumed_or_bound, checkout_attempt=attempt)

    @staticmethod
    def _matching_attempt(
        state: EvaluationState, request: ToolRequest, request_hash: str, amount: int
    ) -> CheckoutAttempt | None:
        arguments = request.arguments
        if not isinstance(arguments, FinancialIntentArguments):
            return None
        return next(
            (
                item
                for item in state.attempts_for(request.mandate_id, arguments.checkout_intent_id)
                if item.request_hash == request_hash
                and item.product_id == arguments.product_id
                and item.quantity == arguments.quantity
                and item.amount_paise == amount
                and item.currency == arguments.currency
            ),
            None,
        )

    @staticmethod
    def _approval_by_id(state: EvaluationState, approval_id: str | None) -> Approval | None:
        if approval_id is None:
            return None
        return next((item for item in state.approvals if item.approval_id == approval_id), None)

    @staticmethod
    def _effect_expiry(
        evaluated_at: datetime, ttl: timedelta, mandate_expires_at: datetime
    ) -> datetime:
        expiry = min(evaluated_at + ttl, mandate_expires_at)
        if expiry <= evaluated_at:
            raise InvalidEffectExpirationError("effect expiry must be after evaluation time")
        return expiry
