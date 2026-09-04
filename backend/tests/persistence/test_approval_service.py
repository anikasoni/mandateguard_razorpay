"""Transactional trusted-human approval lifecycle tests."""

from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from mandateguard.db.models import ApprovalDecisionEventRecord, ApprovalRecord
from mandateguard.db.repositories import (
    ApprovalDecisionAuditRepository,
    ApprovalRepository,
    MandateRepository,
    ProductRepository,
)
from mandateguard.db.session import immediate_policy_session
from mandateguard.domain import Approval, ApprovalStatus, Mandate, Product
from mandateguard.services.approvals import (
    ApprovalBindingMismatchError,
    ApprovalExpiredError,
    ApprovalStateConflictError,
    HumanApprovalService,
)


class SequentialIds:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self, prefix: str) -> str:
        self.count += 1
        return f"{prefix}-{self.count}"


class FailingApprovalAuditRepository(ApprovalDecisionAuditRepository):
    def append(self, **values: Any) -> ApprovalDecisionEventRecord:
        del values
        raise RuntimeError("injected approval audit failure")


def _seed(
    factory: sessionmaker[Session], mandate: Mandate, product: Product, approval: Approval
) -> None:
    with immediate_policy_session(factory) as session:
        MandateRepository(session).add(mandate)
        ProductRepository(session).add(product)
        session.flush()
        ApprovalRepository(session).add(
            approval,
            evaluated_at=approval.expires_at - timedelta(minutes=1),
        )


def _decide(
    service: HumanApprovalService,
    approval: Approval,
    decision: str,
    evaluated_at: datetime,
) -> Any:
    return service.decide(
        mandate_id=approval.mandate_id,
        approval_id=approval.approval_id,
        checkout_intent_id=approval.checkout_intent_id,
        decision=decision,
        evaluated_at=evaluated_at,
    )


@pytest.mark.parametrize(
    ("decision", "status", "live"), [("grant", "granted", 1), ("reject", "rejected", 0)]
)
def test_human_decision_and_identical_replay_are_atomic(
    decision: str,
    status: str,
    live: int,
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
    approval: Approval,
) -> None:
    pending = approval.model_copy(update={"status": ApprovalStatus.PENDING})
    _seed(persistence_session_factory, mandate, product, pending)
    now = pending.expires_at - timedelta(seconds=1)
    service = HumanApprovalService(persistence_session_factory, id_factory=SequentialIds())

    first = _decide(service, pending, decision, now)
    replay = _decide(service, pending, decision, now)

    assert (first.approval.status.value, first.replayed) == (status, False)
    assert (replay.approval.status.value, replay.replayed) == (status, True)
    with persistence_session_factory() as session:
        stored = session.get(ApprovalRecord, pending.approval_id)
        assert stored is not None
        assert (stored.status, stored.live_binding) == (status, live)
        events = session.scalars(
            select(ApprovalDecisionEventRecord).order_by(ApprovalDecisionEventRecord.event_id)
        ).all()
        assert len(events) == 2
        assert [event.replayed for event in events] == [False, True]
        assert all(event.actor_type == "trusted_human" for event in events)


def test_expiry_binding_and_opposite_decision_do_not_mutate_or_audit(
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
    approval: Approval,
) -> None:
    pending = approval.model_copy(update={"status": ApprovalStatus.PENDING})
    _seed(persistence_session_factory, mandate, product, pending)
    service = HumanApprovalService(persistence_session_factory)

    with pytest.raises(ApprovalBindingMismatchError):
        service.decide(
            mandate_id="other-mandate",
            approval_id=pending.approval_id,
            checkout_intent_id=pending.checkout_intent_id,
            decision="grant",
            evaluated_at=pending.expires_at - timedelta(seconds=1),
        )
    with pytest.raises(ApprovalExpiredError):
        _decide(service, pending, "grant", pending.expires_at)

    granted = _decide(service, pending, "grant", pending.expires_at - timedelta(seconds=1))
    assert granted.approval.status.value == "granted"
    with pytest.raises(ApprovalStateConflictError):
        _decide(service, pending, "reject", pending.expires_at - timedelta(seconds=1))

    with persistence_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ApprovalDecisionEventRecord)) == 1


def test_approval_audit_failure_rolls_back_mutation(
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
    approval: Approval,
) -> None:
    pending = approval.model_copy(update={"status": ApprovalStatus.PENDING})
    _seed(persistence_session_factory, mandate, product, pending)
    service = HumanApprovalService(
        persistence_session_factory,
        audit_repository_factory=FailingApprovalAuditRepository,
    )

    with pytest.raises(RuntimeError, match="injected approval audit failure"):
        _decide(service, pending, "grant", pending.expires_at - timedelta(seconds=1))

    with persistence_session_factory() as session:
        stored = session.get(ApprovalRecord, pending.approval_id)
        assert stored is not None
        assert (stored.status, stored.live_binding) == ("pending", 1)
        assert session.scalar(select(func.count()).select_from(ApprovalDecisionEventRecord)) == 0
