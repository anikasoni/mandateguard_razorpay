"""Append-only audit and approval live-binding tests."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from mandateguard.core.config import Settings
from mandateguard.db.models import ApprovalRecord, AuditEventRecord
from mandateguard.db.repositories import ApprovalRepository, MandateRepository, ProductRepository
from mandateguard.db.session import immediate_policy_session
from mandateguard.domain import Approval, ApprovalStatus, Mandate, Product
from mandateguard.services.policy import PolicyService


def _seed_state(session: Session, mandate: Mandate, product: Product) -> None:
    MandateRepository(session).add(mandate)
    ProductRepository(session).add(product)
    session.flush()


def test_partial_live_binding_index_and_expired_history(
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
    approval: Approval,
) -> None:
    now = datetime(2026, 8, 30, 12, tzinfo=approval.expires_at.tzinfo)
    cleanup_at = now + timedelta(hours=1)
    duplicate = approval.model_copy(
        update={"approval_id": "approval-2", "expires_at": cleanup_at + timedelta(hours=1)}
    )
    with immediate_policy_session(persistence_session_factory) as session:
        _seed_state(session, mandate, product)
        repository = ApprovalRepository(session)
        repository.add(approval, evaluated_at=now)
        session.flush()
        repository.release_expired_live_bindings("mandate-1", cleanup_at)
        session.flush()
        repository.add(duplicate, evaluated_at=cleanup_at)

    with persistence_session_factory() as session:
        records = session.scalars(select(ApprovalRecord).order_by(ApprovalRecord.approval_id)).all()
        assert [(item.status, item.live_binding) for item in records] == [
            ("granted", 0),
            ("granted", 1),
        ]


@pytest.mark.parametrize("reverse_order", [False, True])
def test_two_simultaneously_live_exact_bindings_are_rejected_in_either_order(
    reverse_order: bool,
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
    approval: Approval,
) -> None:
    now = datetime(2026, 8, 30, 12, tzinfo=approval.expires_at.tzinfo)
    duplicate = approval.model_copy(update={"approval_id": "approval-duplicate"})
    first, second = (duplicate, approval) if reverse_order else (approval, duplicate)
    with (
        pytest.raises(IntegrityError),
        immediate_policy_session(persistence_session_factory) as session,
    ):
        _seed_state(session, mandate, product)
        repository = ApprovalRepository(session)
        repository.add(first, evaluated_at=now)
        repository.add(second, evaluated_at=now)


@pytest.mark.parametrize(
    ("status", "expiry_offset", "expected"),
    [
        (ApprovalStatus.PENDING, 1, 1),
        (ApprovalStatus.GRANTED, 1, 1),
        (ApprovalStatus.PENDING, 0, 0),
        (ApprovalStatus.GRANTED, -1, 0),
        (ApprovalStatus.REJECTED, 1, 0),
        (ApprovalStatus.REVOKED, 1, 0),
        (ApprovalStatus.CONSUMED, 1, 0),
    ],
)
def test_repository_derives_live_binding_from_domain_state_and_evaluation_time(
    status: ApprovalStatus,
    expiry_offset: int,
    expected: int,
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
    approval: Approval,
) -> None:
    now = datetime(2026, 8, 30, 12, tzinfo=approval.expires_at.tzinfo)
    candidate = approval.model_copy(
        update={"status": status, "expires_at": now + timedelta(seconds=expiry_offset)}
    )
    with immediate_policy_session(persistence_session_factory) as session:
        _seed_state(session, mandate, product)
        ApprovalRepository(session).add(candidate, evaluated_at=now)
    with persistence_session_factory() as session:
        record = session.get(ApprovalRecord, candidate.approval_id)
        assert record is not None
        assert record.live_binding == expected


@pytest.mark.parametrize("target", [ApprovalStatus.REJECTED, ApprovalStatus.REVOKED])
def test_rejection_and_revocation_clear_only_the_live_slot_and_status(
    target: ApprovalStatus,
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
    approval: Approval,
) -> None:
    with immediate_policy_session(persistence_session_factory) as session:
        _seed_state(session, mandate, product)
        repository = ApprovalRepository(session)
        repository.add(
            approval,
            evaluated_at=datetime(2026, 8, 30, 12, tzinfo=approval.expires_at.tzinfo),
        )
        session.flush()
        changed = repository.deactivate(approval.approval_id, target)
        assert changed.status is target
    with persistence_session_factory() as session:
        record = session.get(ApprovalRecord, approval.approval_id)
        assert record is not None
        assert record.live_binding == 0


def test_consumption_clears_live_slot(
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
    approval: Approval,
) -> None:
    with immediate_policy_session(persistence_session_factory) as session:
        _seed_state(session, mandate, product)
        repository = ApprovalRepository(session)
        repository.add(
            approval,
            evaluated_at=datetime(2026, 8, 30, 12, tzinfo=approval.expires_at.tzinfo),
        )
        session.flush()
        consumed = repository.consume_granted(approval.approval_id)
        assert consumed.status is ApprovalStatus.CONSUMED
    with persistence_session_factory() as session:
        record = session.get(ApprovalRecord, approval.approval_id)
        assert record is not None
        assert record.live_binding == 0


def _create_audit(
    persistence_session_factory: sessionmaker[Session], mandate: Mandate, product: Product
) -> tuple[str, str]:
    with persistence_session_factory.begin() as session:
        _seed_state(session, mandate, product)
    result = PolicyService(persistence_session_factory, Settings(_env_file=None)).evaluate(
        {
            "request_id": "request-audit",
            "mandate_id": "mandate-1",
            "tool": "get_product",
            "arguments": {"product_id": "product-1", "currency": "INR"},
        },
        evaluated_at=datetime(2026, 8, 30, 12, tzinfo=mandate.expires_at.tzinfo),
    )
    with persistence_session_factory() as session:
        record = session.get(AuditEventRecord, result.audit_event_id)
        assert record is not None
        return record.event_id, record.reason


def _assert_unchanged(
    persistence_session_factory: sessionmaker[Session], event_id: str, reason: str
) -> None:
    with persistence_session_factory() as session:
        record = session.get(AuditEventRecord, event_id)
        assert record is not None
        assert record.reason == reason
        assert session.scalar(select(func.count()).select_from(AuditEventRecord)) == 1


def test_audit_events_are_append_only_through_sqlalchemy_core(
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
) -> None:
    event_id, reason = _create_audit(persistence_session_factory, mandate, product)

    with pytest.raises(IntegrityError), persistence_session_factory.begin() as session:
        session.execute(
            update(AuditEventRecord)
            .where(AuditEventRecord.event_id == event_id)
            .values(reason="tampered")
        )
    with pytest.raises(IntegrityError), persistence_session_factory.begin() as session:
        session.execute(delete(AuditEventRecord).where(AuditEventRecord.event_id == event_id))
    _assert_unchanged(persistence_session_factory, event_id, reason)


def test_audit_events_are_append_only_through_raw_sql(
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
) -> None:
    event_id, reason = _create_audit(persistence_session_factory, mandate, product)
    with pytest.raises(IntegrityError), persistence_session_factory.begin() as session:
        session.connection().exec_driver_sql(
            "UPDATE audit_events SET reason = 'tampered' WHERE event_id = ?", (event_id,)
        )
    with pytest.raises(IntegrityError), persistence_session_factory.begin() as session:
        session.connection().exec_driver_sql(
            "DELETE FROM audit_events WHERE event_id = ?", (event_id,)
        )
    _assert_unchanged(persistence_session_factory, event_id, reason)


def test_audit_events_are_append_only_through_orm_mutation_and_delete(
    persistence_session_factory: sessionmaker[Session],
    mandate: Mandate,
    product: Product,
) -> None:
    event_id, reason = _create_audit(persistence_session_factory, mandate, product)
    with pytest.raises(IntegrityError), persistence_session_factory.begin() as session:
        record = session.get(AuditEventRecord, event_id)
        assert record is not None
        record.reason = "tampered"
        session.flush()
    with pytest.raises(IntegrityError), persistence_session_factory.begin() as session:
        record = session.get(AuditEventRecord, event_id)
        assert record is not None
        session.delete(record)
        session.flush()
    _assert_unchanged(persistence_session_factory, event_id, reason)
