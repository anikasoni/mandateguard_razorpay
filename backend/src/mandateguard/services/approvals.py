"""Transactional lifecycle for decisions made by a trusted human."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import uuid4

from sqlalchemy.orm import Session

from mandateguard.db.repositories import (
    ApprovalDecisionAuditRepository,
    ApprovalRepository,
)
from mandateguard.db.session import SessionFactory, immediate_policy_session
from mandateguard.domain.enums import ApprovalStatus
from mandateguard.domain.models import Approval
from mandateguard.domain.validation import normalize_utc

type HumanDecision = Literal["grant", "reject"]
type IdFactory = Callable[[str], str]
type ApprovalDecisionAuditRepositoryFactory = Callable[[Session], ApprovalDecisionAuditRepository]


class ApprovalNotFoundError(LookupError):
    pass


class ApprovalBindingMismatchError(RuntimeError):
    pass


class ApprovalExpiredError(RuntimeError):
    pass


class ApprovalStateConflictError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class HumanApprovalResult:
    approval: Approval
    decision: HumanDecision
    evaluated_at: datetime
    replayed: bool
    audit_event_id: str


def _default_id_factory(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


class HumanApprovalService:
    """Grant or reject an exact pending approval and audit the action atomically."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        id_factory: IdFactory = _default_id_factory,
        audit_repository_factory: ApprovalDecisionAuditRepositoryFactory = (
            ApprovalDecisionAuditRepository
        ),
    ) -> None:
        self._session_factory = session_factory
        self._id_factory = id_factory
        self._audit_repository_factory = audit_repository_factory

    def decide(
        self,
        *,
        mandate_id: str,
        approval_id: str,
        checkout_intent_id: str,
        decision: HumanDecision,
        evaluated_at: datetime,
    ) -> HumanApprovalResult:
        timestamp = normalize_utc(evaluated_at)
        provisional: HumanApprovalResult | None = None
        target = ApprovalStatus.GRANTED if decision == "grant" else ApprovalStatus.REJECTED

        with immediate_policy_session(self._session_factory) as session:
            approvals = ApprovalRepository(session)
            approval = approvals.get(approval_id)
            if approval is None:
                raise ApprovalNotFoundError("approval not found")
            if (
                approval.mandate_id != mandate_id
                or approval.checkout_intent_id != checkout_intent_id
            ):
                raise ApprovalBindingMismatchError("approval binding does not match")

            replayed = approval.status is target
            if not replayed:
                if approval.status is not ApprovalStatus.PENDING:
                    raise ApprovalStateConflictError("approval is not pending")
                if not approval.is_live_at(timestamp):
                    raise ApprovalExpiredError("approval has expired")
                approval = approvals.decide_pending(
                    approval,
                    status=target,
                    evaluated_at=timestamp,
                )

            audit_event_id = self._id_factory("approval-audit")
            self._audit_repository_factory(session).append(
                event_id=audit_event_id,
                approval=approval,
                requested_decision=decision,
                evaluated_at=timestamp,
                replayed=replayed,
            )
            session.flush()
            provisional = HumanApprovalResult(
                approval=approval,
                decision=decision,
                evaluated_at=timestamp,
                replayed=replayed,
                audit_event_id=audit_event_id,
            )

        if provisional is None:
            raise RuntimeError("approval transaction committed without a result")
        return provisional
