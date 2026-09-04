"""Transactional PolicyService integration and failure tests."""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import pytest
from pydantic import TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from mandateguard.core.config import Settings
from mandateguard.db.models import ApprovalRecord, AuditEventRecord, CheckoutAttemptRecord
from mandateguard.db.repositories import (
    ApprovalRepository,
    AuditRepository,
    MandateRepository,
    ProductRepository,
    RepositoryConflictError,
)
from mandateguard.db.session import immediate_policy_session
from mandateguard.domain import (
    Approval,
    ApprovalStatus,
    CheckoutAttempt,
    CheckoutStatus,
    DecisionOutcome,
    EvaluationState,
    Mandate,
    Product,
    RuleId,
    ToolRequest,
)
from mandateguard.policy import PolicyEngine
from mandateguard.policy.canonical import intent_hash
from mandateguard.services.policy import PolicyService

TypeAdapterForTest: TypeAdapter[ToolRequest] = TypeAdapter(ToolRequest)


class SequentialIds:
    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def __call__(self, prefix: str) -> str:
        value = self._counts.get(prefix, 0) + 1
        self._counts[prefix] = value
        return f"{prefix}-{value}"


class FailingAuditRepository(AuditRepository):
    def append(self, **values: Any) -> AuditEventRecord:
        del values
        raise RuntimeError("injected audit failure")


def _seed(
    factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
    *,
    approvals: tuple[Approval, ...] = (),
    attempts: tuple[CheckoutAttempt, ...] = (),
) -> None:
    with immediate_policy_session(factory) as session:
        MandateRepository(session).add(mandate)
        ProductRepository(session).add(product)
        session.flush()
        approval_repository = ApprovalRepository(session)
        for approval in approvals:
            approval_repository.add(
                approval,
                evaluated_at=datetime(2026, 8, 30, 12, tzinfo=approval.expires_at.tzinfo),
            )
        session.flush()
        from mandateguard.db.repositories import CheckoutAttemptRepository

        attempt_repository = CheckoutAttemptRepository(session)
        for attempt in attempts:
            attempt_repository.add(attempt)


def _request(tool: str = "create_checkout", **changes: object) -> dict[str, object]:
    if tool == "get_product":
        arguments: dict[str, object] = {"product_id": "product-1", "currency": "INR"}
    else:
        arguments = {
            "product_id": "product-1",
            "checkout_intent_id": "intent-1",
            "quantity": 2,
            "currency": "INR",
            "quoted_unit_price_paise": 5_000,
            "price_version": 7,
            "inventory_version": 4,
            "approval_id": None,
        }
        arguments.update(changes)
    return {
        "request_id": "request-1",
        "mandate_id": "mandate-1",
        "tool": tool,
        "arguments": arguments,
    }


def _service(
    factory: sessionmaker[Session],
    ids: SequentialIds,
    *,
    audit_factory: Callable[[Session], AuditRepository] = AuditRepository,
) -> PolicyService:
    return PolicyService(
        factory,
        Settings(_env_file=None),
        id_factory=ids,
        audit_repository_factory=audit_factory,
    )


def test_checkout_allow_reserves_and_audits_atomically(
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
) -> None:
    _seed(persistence_session_factory, mandate, product)
    ids = SequentialIds()
    result = _service(persistence_session_factory, ids).evaluate(
        _request(), evaluated_at=datetime(2026, 8, 30, 12, tzinfo=mandate.expires_at.tzinfo)
    )

    assert result.decision.outcome is DecisionOutcome.ALLOW
    assert result.checkout_attempt is not None
    assert result.checkout_attempt.status is CheckoutStatus.RESERVED
    assert len(result.checkout_attempt.idempotency_key) == 64
    with persistence_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(CheckoutAttemptRecord)) == 1
        audit = session.scalar(select(AuditEventRecord))
        assert audit is not None
        assert audit.effect_attempt_id == result.checkout_attempt.attempt_id
        assert audit.effect_approval_id is None


def test_expired_reserved_replay_is_strictly_read_only(
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
) -> None:
    _seed(persistence_session_factory, mandate, product)
    ids = SequentialIds()
    service = _service(persistence_session_factory, ids)
    first = service.evaluate(
        _request(), evaluated_at=datetime(2026, 8, 30, 12, tzinfo=mandate.expires_at.tzinfo)
    )
    assert first.checkout_attempt is not None
    original = first.checkout_attempt

    replay = service.evaluate(
        _request(),
        evaluated_at=datetime(2026, 8, 30, 12, tzinfo=mandate.expires_at.tzinfo)
        + timedelta(minutes=6),
    )
    assert replay.decision.execution_mode.value == "replay"
    assert replay.checkout_attempt == original
    assert replay.approval is None
    with persistence_session_factory() as session:
        stored = session.get(CheckoutAttemptRecord, original.attempt_id)
        assert stored is not None
        assert stored.reservation_expires_at == original.reservation_expires_at
        assert session.scalar(select(func.count()).select_from(CheckoutAttemptRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ApprovalRecord)) == 0
        assert session.scalar(select(func.count()).select_from(AuditEventRecord)) == 2


def test_request_approval_create_then_replay_is_read_only(
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
) -> None:
    threshold_mandate = mandate.model_copy(update={"approval_threshold_paise": 10_000})
    _seed(persistence_session_factory, threshold_mandate, product)
    ids = SequentialIds()
    service = _service(persistence_session_factory, ids)
    now = datetime(2026, 8, 30, 12, tzinfo=mandate.expires_at.tzinfo)
    first = service.evaluate(_request("request_approval"), evaluated_at=now)
    second = service.evaluate(_request("request_approval"), evaluated_at=now)

    assert first.approval is not None
    assert first.approval.status is ApprovalStatus.PENDING
    assert second.decision.execution_mode.value == "replay"
    assert second.approval == first.approval
    with persistence_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ApprovalRecord)) == 1
        stored_approval = session.get(ApprovalRecord, first.approval.approval_id)
        assert stored_approval is not None
        assert stored_approval.live_binding == 1
        assert session.scalar(select(func.count()).select_from(AuditEventRecord)) == 2
        audits = session.scalars(select(AuditEventRecord).order_by(AuditEventRecord.event_id)).all()
        assert [event.effect_approval_id for event in audits] == [
            first.approval.approval_id,
            first.approval.approval_id,
        ]
        assert all(event.effect_attempt_id is None for event in audits)


def test_checkout_request_approval_outcome_has_no_financial_mutation(
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
) -> None:
    threshold_mandate = mandate.model_copy(update={"approval_threshold_paise": 10_000})
    _seed(persistence_session_factory, threshold_mandate, product)
    result = _service(persistence_session_factory, SequentialIds()).evaluate(
        _request(), evaluated_at=datetime(2026, 8, 30, 12, tzinfo=mandate.expires_at.tzinfo)
    )
    assert result.decision.outcome is DecisionOutcome.REQUEST_APPROVAL
    assert result.approval is None
    assert result.checkout_attempt is None
    with persistence_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ApprovalRecord)) == 0
        assert session.scalar(select(func.count()).select_from(CheckoutAttemptRecord)) == 0
        assert session.scalar(select(func.count()).select_from(AuditEventRecord)) == 1


def test_malformed_is_mg001_and_unknown_mandate_is_mg003(
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
) -> None:
    _seed(persistence_session_factory, mandate, product)
    service = _service(persistence_session_factory, SequentialIds())
    now = datetime(2026, 8, 30, 12, tzinfo=mandate.expires_at.tzinfo)
    malformed = service.evaluate({"secret": object()}, evaluated_at=now)
    unknown_raw = _request("get_product")
    unknown_raw["mandate_id"] = "missing-mandate"
    unknown = service.evaluate(unknown_raw, evaluated_at=now)

    assert (malformed.decision.rule_id, malformed.decision.reason) == (
        RuleId.REQUEST_CONTRACT,
        "request_contract_invalid",
    )
    assert (unknown.decision.rule_id, unknown.decision.reason) == (
        RuleId.MANDATE_STATUS,
        "mandate_not_found",
    )
    with persistence_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(AuditEventRecord)) == 2
        assert session.scalar(select(func.count()).select_from(ApprovalRecord)) == 0
        assert session.scalar(select(func.count()).select_from(CheckoutAttemptRecord)) == 0


def test_malformed_audit_redacts_all_raw_envelope_values(
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
) -> None:
    _seed(persistence_session_factory, mandate, product)
    service = _service(persistence_session_factory, SequentialIds())
    now = datetime(2026, 8, 30, 12, tzinfo=mandate.expires_at.tzinfo)
    secret = "SECRET-envelope-value"

    result = service.evaluate(
        {
            "request_id": secret,
            "mandate_id": mandate.mandate_id,
            "tool": secret,
            "arguments": {"password": secret, "quantity": object()},
        },
        evaluated_at=now,
    )

    assert result.decision.rule_id is RuleId.REQUEST_CONTRACT
    with persistence_session_factory() as session:
        event = session.get(AuditEventRecord, result.audit_event_id)
        assert event is not None
        stored = " ".join((event.arguments_json, event.request_envelope_json, event.evidence_json))
        assert secret not in stored


def test_malformed_mg001_is_identical_before_and_after_mandate_exists(
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
) -> None:
    service = _service(persistence_session_factory, SequentialIds())
    now = datetime(2026, 8, 30, 12, tzinfo=mandate.expires_at.tzinfo)
    raw = {"mandate_id": mandate.mandate_id, "unsupported": object()}

    without_state = service.evaluate(raw, evaluated_at=now)
    _seed(persistence_session_factory, mandate, product)
    with_state = service.evaluate(raw, evaluated_at=now)

    assert without_state.decision == with_state.decision
    assert with_state.decision.reason == "request_contract_invalid"


def test_expired_retryable_attempt_renews_same_identity(
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
) -> None:
    raw = _request()
    parsed = TypeAdapterForTest.validate_python(raw)
    request_hash = intent_hash(parsed)
    assert request_hash is not None
    now = datetime(2026, 8, 30, 12, tzinfo=mandate.expires_at.tzinfo)
    attempt = CheckoutAttempt(
        attempt_id="retry-attempt",
        idempotency_key="retry-key",
        mandate_id="mandate-1",
        checkout_intent_id="intent-1",
        request_hash=request_hash,
        product_id="product-1",
        quantity=2,
        amount_paise=10_000,
        currency="INR",
        status=CheckoutStatus.RETRYABLE_FAILED,
        reservation_expires_at=now,
    )
    _seed(persistence_session_factory, mandate, product, attempts=(attempt,))
    result = _service(persistence_session_factory, SequentialIds()).evaluate(raw, evaluated_at=now)
    assert result.decision.execution_mode.value == "retry_existing"
    assert result.checkout_attempt is not None
    assert result.checkout_attempt.attempt_id == "retry-attempt"
    assert result.checkout_attempt.idempotency_key == "retry-key"
    assert result.checkout_attempt.reservation_expires_at == now + timedelta(minutes=5)


def test_audit_failure_rolls_back_checkout_effect(
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
) -> None:
    _seed(persistence_session_factory, mandate, product)
    service = _service(
        persistence_session_factory,
        SequentialIds(),
        audit_factory=FailingAuditRepository,
    )
    with pytest.raises(RuntimeError, match="injected audit failure"):
        service.evaluate(
            _request(),
            evaluated_at=datetime(2026, 8, 30, 12, tzinfo=mandate.expires_at.tzinfo),
        )
    with persistence_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(CheckoutAttemptRecord)) == 0
        assert session.scalar(select(func.count()).select_from(AuditEventRecord)) == 0


def test_injected_flush_failure_rolls_back_and_exposes_no_result(
    monkeypatch: pytest.MonkeyPatch,
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
) -> None:
    _seed(persistence_session_factory, mandate, product)
    original_flush = Session.flush

    def fail_flush(session: Session, objects: object = None) -> None:
        del session, objects
        raise RuntimeError("injected flush failure")

    with monkeypatch.context() as context:
        context.setattr(Session, "flush", fail_flush)
        with pytest.raises(RuntimeError, match="injected flush failure"):
            _service(persistence_session_factory, SequentialIds()).evaluate(
                _request(),
                evaluated_at=datetime(2026, 8, 30, 12, tzinfo=mandate.expires_at.tzinfo),
            )

    assert Session.flush is original_flush
    with persistence_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(CheckoutAttemptRecord)) == 0
        assert session.scalar(select(func.count()).select_from(AuditEventRecord)) == 0


def test_compare_and_set_failure_returns_no_result_or_partial_effect(
    monkeypatch: pytest.MonkeyPatch,
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
    approval: Approval,
) -> None:
    threshold_mandate = mandate.model_copy(update={"approval_threshold_paise": 10_000})
    _seed(persistence_session_factory, threshold_mandate, product, approvals=(approval,))

    def fail_consume(repository: ApprovalRepository, approval_id: str) -> Approval:
        del repository, approval_id
        raise RepositoryConflictError("injected compare-and-set failure")

    monkeypatch.setattr(ApprovalRepository, "consume_granted", fail_consume)
    with pytest.raises(RepositoryConflictError, match="injected compare-and-set failure"):
        _service(persistence_session_factory, SequentialIds()).evaluate(
            _request(approval_id="approval-1"),
            evaluated_at=datetime(2026, 8, 30, 12, tzinfo=mandate.expires_at.tzinfo),
        )
    with persistence_session_factory() as session:
        stored = session.get(ApprovalRecord, "approval-1")
        assert stored is not None
        assert (stored.status, stored.live_binding) == ("granted", 1)
        assert session.scalar(select(func.count()).select_from(CheckoutAttemptRecord)) == 0
        assert session.scalar(select(func.count()).select_from(AuditEventRecord)) == 0


def test_constraint_failure_rolls_back_without_audit(
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
) -> None:
    prior = CheckoutAttempt(
        attempt_id="attempt-1",
        idempotency_key="prior-key",
        mandate_id="mandate-1",
        checkout_intent_id="prior-intent",
        request_hash="0" * 64,
        product_id="product-1",
        quantity=1,
        amount_paise=0,
        currency="INR",
        status=CheckoutStatus.COMPLETED,
    )
    _seed(persistence_session_factory, mandate, product, attempts=(prior,))
    with pytest.raises(IntegrityError):
        _service(persistence_session_factory, SequentialIds()).evaluate(
            _request(),
            evaluated_at=datetime(2026, 8, 30, 12, tzinfo=mandate.expires_at.tzinfo),
        )
    with persistence_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(CheckoutAttemptRecord)) == 1
        assert session.scalar(select(func.count()).select_from(AuditEventRecord)) == 0


@pytest.mark.parametrize("status", tuple(CheckoutStatus))
@pytest.mark.parametrize(
    ("relation", "offset"),
    [("before", -1), ("exact", 0), ("after", 1)],
)
def test_every_attempt_status_matches_phase2a_before_at_and_after_expiry(
    status: CheckoutStatus,
    relation: str,
    offset: int,
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
) -> None:
    raw = _request()
    parsed = TypeAdapterForTest.validate_python(raw)
    request_hash = intent_hash(parsed)
    assert request_hash is not None
    expiry = datetime(2026, 8, 30, 12, tzinfo=mandate.expires_at.tzinfo)
    reservation_expires_at = (
        expiry
        if status
        in {CheckoutStatus.RESERVED, CheckoutStatus.CREATED, CheckoutStatus.RETRYABLE_FAILED}
        else None
    )
    attempt = CheckoutAttempt(
        attempt_id=f"attempt-{status.value}",
        idempotency_key=f"key-{status.value}",
        mandate_id="mandate-1",
        checkout_intent_id="intent-1",
        request_hash=request_hash,
        product_id="product-1",
        quantity=2,
        amount_paise=10_000,
        currency="INR",
        status=status,
        reservation_expires_at=reservation_expires_at,
    )
    evaluated_at = expiry + timedelta(seconds=offset)
    expected = PolicyEngine().evaluate(
        raw,
        EvaluationState(
            mandate=mandate,
            products=(product,),
            checkout_attempts=(attempt,),
        ),
        evaluated_at=evaluated_at,
    )
    _seed(persistence_session_factory, mandate, product, attempts=(attempt,))
    actual = _service(persistence_session_factory, SequentialIds()).evaluate(
        raw, evaluated_at=evaluated_at
    )

    assert actual.decision == expected, (status, relation)
    if expected.execution_mode.value == "replay":
        assert actual.checkout_attempt == attempt
