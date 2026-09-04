"""Session-bound repositories for persisted policy state and decisions."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast

from sqlalchemy import Select, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from mandateguard.db.mappers import (
    approval_from_record,
    approval_to_record,
    audit_record_from_decision,
    checkout_attempt_from_record,
    checkout_attempt_to_record,
    decision_from_audit_record,
    mandate_from_record,
    mandate_to_records,
    product_from_record,
    product_to_record,
)
from mandateguard.db.models import (
    ApprovalRecord,
    AuditEventRecord,
    CheckoutAttemptRecord,
    MandateCategoryScopeRecord,
    MandateMerchantScopeRecord,
    MandateRecord,
    ProductRecord,
)
from mandateguard.domain.enums import ApprovalStatus, CheckoutStatus
from mandateguard.domain.models import (
    Approval,
    CheckoutAttempt,
    GuardDecision,
    Mandate,
    Product,
)
from mandateguard.domain.state import EvaluationState


class RepositoryConflictError(RuntimeError):
    """Raised when persisted state changed after deterministic evaluation."""


def _require_immediate(session: Session) -> None:
    if session.info.get("mandateguard_begin_immediate") is not True:
        raise RuntimeError("live approval binding changes require BEGIN IMMEDIATE")


class MandateRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, mandate: Mandate) -> None:
        record, merchants, categories = mandate_to_records(mandate)
        self._session.add(record)
        self._session.flush()
        self._session.add_all((*merchants, *categories))

    def get(self, mandate_id: str) -> Mandate | None:
        record = self._session.get(MandateRecord, mandate_id)
        if record is None:
            return None
        merchants = self._session.scalars(
            select(MandateMerchantScopeRecord)
            .where(MandateMerchantScopeRecord.mandate_id == mandate_id)
            .order_by(MandateMerchantScopeRecord.merchant_id)
        ).all()
        categories = self._session.scalars(
            select(MandateCategoryScopeRecord)
            .where(MandateCategoryScopeRecord.mandate_id == mandate_id)
            .order_by(MandateCategoryScopeRecord.category_id)
        ).all()
        return mandate_from_record(record, merchants, categories)


class ProductRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, product: Product) -> None:
        self._session.add(product_to_record(product))

    def get(self, product_id: str) -> Product | None:
        record = self._session.get(ProductRecord, product_id)
        return product_from_record(record) if record is not None else None


class ApprovalRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, approval: Approval, *, evaluated_at: datetime) -> None:
        _require_immediate(self._session)
        self._session.add(approval_to_record(approval, evaluated_at=evaluated_at))

    def get(self, approval_id: str) -> Approval | None:
        record = self._session.get(ApprovalRecord, approval_id)
        return approval_from_record(record) if record is not None else None

    def list_for_mandate(self, mandate_id: str) -> tuple[Approval, ...]:
        records = self._session.scalars(
            select(ApprovalRecord)
            .where(ApprovalRecord.mandate_id == mandate_id)
            .order_by(ApprovalRecord.approval_id)
        ).all()
        return tuple(approval_from_record(record) for record in records)

    def release_expired_live_bindings(self, mandate_id: str, evaluated_at: datetime) -> int:
        _require_immediate(self._session)
        result = self._session.execute(
            update(ApprovalRecord)
            .where(
                ApprovalRecord.mandate_id == mandate_id,
                ApprovalRecord.live_binding == 1,
                ApprovalRecord.status.in_(
                    (ApprovalStatus.PENDING.value, ApprovalStatus.GRANTED.value)
                ),
                ApprovalRecord.expires_at <= evaluated_at,
            )
            .values(live_binding=0)
        )
        return int(cast(CursorResult[Any], result).rowcount)

    def consume_granted(self, approval_id: str) -> Approval:
        _require_immediate(self._session)
        result = self._session.execute(
            update(ApprovalRecord)
            .where(
                ApprovalRecord.approval_id == approval_id,
                ApprovalRecord.status == ApprovalStatus.GRANTED.value,
            )
            .values(status=ApprovalStatus.CONSUMED.value, live_binding=0)
        )
        if cast(CursorResult[Any], result).rowcount != 1:
            raise RepositoryConflictError("granted approval could not be consumed")
        approval = self.get(approval_id)
        if approval is None:
            raise RepositoryConflictError("consumed approval disappeared")
        return approval

    def deactivate(self, approval_id: str, status: ApprovalStatus) -> Approval:
        _require_immediate(self._session)
        if status not in {ApprovalStatus.REJECTED, ApprovalStatus.REVOKED}:
            raise ValueError("only rejection or revocation can deactivate an approval")
        result = self._session.execute(
            update(ApprovalRecord)
            .where(
                ApprovalRecord.approval_id == approval_id,
                ApprovalRecord.status.in_(
                    (ApprovalStatus.PENDING.value, ApprovalStatus.GRANTED.value)
                ),
            )
            .values(status=status.value, live_binding=0)
        )
        if cast(CursorResult[Any], result).rowcount != 1:
            raise RepositoryConflictError("live approval could not be deactivated")
        approval = self.get(approval_id)
        if approval is None:
            raise RepositoryConflictError("deactivated approval disappeared")
        return approval


class CheckoutAttemptRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, attempt: CheckoutAttempt) -> None:
        self._session.add(checkout_attempt_to_record(attempt))

    def get_by_intent(self, mandate_id: str, intent_id: str) -> CheckoutAttempt | None:
        record = self._session.scalar(
            select(CheckoutAttemptRecord).where(
                CheckoutAttemptRecord.mandate_id == mandate_id,
                CheckoutAttemptRecord.checkout_intent_id == intent_id,
            )
        )
        return checkout_attempt_from_record(record) if record is not None else None

    def list_for_mandate(self, mandate_id: str) -> tuple[CheckoutAttempt, ...]:
        records = self._session.scalars(
            select(CheckoutAttemptRecord)
            .where(CheckoutAttemptRecord.mandate_id == mandate_id)
            .order_by(CheckoutAttemptRecord.attempt_id)
        ).all()
        return tuple(checkout_attempt_from_record(record) for record in records)

    def renew_retry_reservation(
        self,
        attempt_id: str,
        *,
        reservation_expires_at: datetime,
        approval_id: str | None,
    ) -> CheckoutAttempt:
        values: dict[str, object] = {"reservation_expires_at": reservation_expires_at}
        if approval_id is not None:
            values["approval_id"] = approval_id
        result = self._session.execute(
            update(CheckoutAttemptRecord)
            .where(
                CheckoutAttemptRecord.attempt_id == attempt_id,
                CheckoutAttemptRecord.status == CheckoutStatus.RETRYABLE_FAILED.value,
            )
            .values(**values)
        )
        if cast(CursorResult[Any], result).rowcount != 1:
            raise RepositoryConflictError("retryable attempt could not be renewed")
        record = self._session.get(CheckoutAttemptRecord, attempt_id)
        if record is None:
            raise RepositoryConflictError("renewed attempt disappeared")
        self._session.refresh(record)
        return checkout_attempt_from_record(record)


class EvaluationStateRepository:
    def __init__(self, session: Session) -> None:
        self._mandates = MandateRepository(session)
        self._products = ProductRepository(session)
        self._approvals = ApprovalRepository(session)
        self._attempts = CheckoutAttemptRepository(session)

    def load(self, mandate_id: str, *, product_id: str | None = None) -> EvaluationState | None:
        mandate = self._mandates.get(mandate_id)
        if mandate is None:
            return None
        product = self._products.get(product_id) if product_id is not None else None
        return EvaluationState(
            mandate=mandate,
            products=(product,) if product is not None else (),
            approvals=self._approvals.list_for_mandate(mandate_id),
            checkout_attempts=self._attempts.list_for_mandate(mandate_id),
        )


class AuditRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def append(
        self,
        *,
        event_id: str,
        decision: GuardDecision,
        arguments: Mapping[str, object],
        effect_approval_id: str | None = None,
        effect_attempt_id: str | None = None,
    ) -> AuditEventRecord:
        record = audit_record_from_decision(
            event_id=event_id,
            decision=decision,
            arguments=arguments,
            effect_approval_id=effect_approval_id,
            effect_attempt_id=effect_attempt_id,
        )
        self._session.add(record)
        return record

    def list_for_mandate(self, mandate_id: str) -> tuple[GuardDecision, ...]:
        statement: Select[tuple[AuditEventRecord]] = (
            select(AuditEventRecord)
            .where(AuditEventRecord.mandate_id == mandate_id)
            .order_by(AuditEventRecord.evaluated_at, AuditEventRecord.event_id)
        )
        return tuple(
            decision_from_audit_record(record) for record in self._session.scalars(statement)
        )
