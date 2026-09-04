"""SQLAlchemy records for persisted Phase 2A policy state and decisions."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from mandateguard.db.base import Base
from mandateguard.db.types import UTCDateTime

MAX_DB_INTEGER = 2**63 - 1


def _identifier_check(column: str) -> str:
    return (
        f"length({column}) BETWEEN 1 AND 128 "
        f"AND substr({column}, 1, 1) GLOB '[A-Za-z0-9]' "
        f"AND {column} NOT GLOB '*[^A-Za-z0-9_.:-]*'"
    )


def _canonical_id_check(column: str) -> str:
    return (
        f"length({column}) BETWEEN 1 AND 64 "
        f"AND substr({column}, 1, 1) GLOB '[a-z0-9]' "
        f"AND {column} NOT GLOB '*[^a-z0-9_-]*'"
    )


def _hash_check(column: str) -> str:
    return f"length({column}) = 64 AND {column} NOT GLOB '*[^0-9a-f]*'"


def _non_negative_integer_check(column: str) -> str:
    return f"typeof({column}) = 'integer' AND {column} BETWEEN 0 AND {MAX_DB_INTEGER}"


def _positive_integer_check(column: str) -> str:
    return f"typeof({column}) = 'integer' AND {column} BETWEEN 1 AND {MAX_DB_INTEGER}"


class MandateRecord(Base):
    __tablename__ = "mandates"
    __table_args__ = (
        CheckConstraint(_identifier_check("mandate_id"), name="mandate_id_format"),
        CheckConstraint(
            "status IN ('active', 'revoked', 'fulfilled')", name="mandate_status_values"
        ),
        CheckConstraint("currency = 'INR'", name="mandate_currency_inr"),
        CheckConstraint(
            _non_negative_integer_check("total_budget_paise"), name="total_budget_bounds"
        ),
        CheckConstraint(
            _non_negative_integer_check("per_item_cap_paise"), name="per_item_cap_bounds"
        ),
        CheckConstraint(
            _non_negative_integer_check("approval_threshold_paise"),
            name="approval_threshold_bounds",
        ),
    )

    mandate_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    total_budget_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    per_item_cap_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    approval_threshold_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class MandateMerchantScopeRecord(Base):
    __tablename__ = "mandate_merchant_scopes"
    __table_args__ = (
        CheckConstraint(_canonical_id_check("merchant_id"), name="merchant_id_format"),
    )

    mandate_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("mandates.mandate_id", ondelete="CASCADE"), primary_key=True
    )
    merchant_id: Mapped[str] = mapped_column(String(64), primary_key=True)


class MandateCategoryScopeRecord(Base):
    __tablename__ = "mandate_category_scopes"
    __table_args__ = (
        CheckConstraint(_canonical_id_check("category_id"), name="category_id_format"),
    )

    mandate_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("mandates.mandate_id", ondelete="CASCADE"), primary_key=True
    )
    category_id: Mapped[str] = mapped_column(String(64), primary_key=True)


class ProductRecord(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint(_identifier_check("product_id"), name="product_id_format"),
        CheckConstraint(_canonical_id_check("merchant_id"), name="product_merchant_format"),
        CheckConstraint(_canonical_id_check("category_id"), name="product_category_format"),
        CheckConstraint("currency = 'INR'", name="product_currency_inr"),
        CheckConstraint(_non_negative_integer_check("unit_price_paise"), name="unit_price_bounds"),
        CheckConstraint(
            _non_negative_integer_check("inventory_count"), name="inventory_count_bounds"
        ),
        CheckConstraint(_non_negative_integer_check("price_version"), name="price_version_bounds"),
        CheckConstraint(
            _non_negative_integer_check("inventory_version"), name="inventory_version_bounds"
        ),
        CheckConstraint("typeof(active) = 'integer' AND active IN (0, 1)", name="active_boolean"),
    )

    product_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    category_id: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    unit_price_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    inventory_count: Mapped[int] = mapped_column(Integer, nullable=False)
    price_version: Mapped[int] = mapped_column(Integer, nullable=False)
    inventory_version: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    offer_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class ApprovalRecord(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        CheckConstraint(_identifier_check("approval_id"), name="approval_id_format"),
        CheckConstraint(_identifier_check("checkout_intent_id"), name="approval_intent_format"),
        CheckConstraint(_hash_check("request_hash"), name="approval_request_hash_format"),
        CheckConstraint(_non_negative_integer_check("amount_paise"), name="approval_amount_bounds"),
        CheckConstraint("currency = 'INR'", name="approval_currency_inr"),
        CheckConstraint(
            "status IN ('pending', 'granted', 'rejected', 'revoked', 'consumed')",
            name="approval_status_values",
        ),
        CheckConstraint(
            "typeof(live_binding) = 'integer' AND live_binding IN (0, 1)",
            name="approval_live_binding_boolean",
        ),
        CheckConstraint(
            "live_binding = 0 OR status IN ('pending', 'granted')",
            name="live_binding_requires_live_status",
        ),
        UniqueConstraint(
            "mandate_id",
            "approval_id",
            "checkout_intent_id",
            "request_hash",
            "amount_paise",
            "currency",
            name="uq_approvals_exact_binding",
        ),
        Index("ix_approvals_mandate_intent", "mandate_id", "checkout_intent_id"),
        Index(
            "uq_approvals_live_binding",
            "mandate_id",
            "checkout_intent_id",
            "request_hash",
            "amount_paise",
            "currency",
            unique=True,
            sqlite_where=text("live_binding = 1 AND status IN ('pending', 'granted')"),
        ),
    )

    approval_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    mandate_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("mandates.mandate_id", ondelete="RESTRICT"), nullable=False
    )
    checkout_intent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    live_binding: Mapped[int] = mapped_column(Integer, nullable=False)


class CheckoutAttemptRecord(Base):
    __tablename__ = "checkout_attempts"
    __table_args__ = (
        CheckConstraint(_identifier_check("attempt_id"), name="attempt_id_format"),
        CheckConstraint(_identifier_check("idempotency_key"), name="idempotency_key_format"),
        CheckConstraint(_identifier_check("checkout_intent_id"), name="attempt_intent_format"),
        CheckConstraint(_hash_check("request_hash"), name="attempt_request_hash_format"),
        CheckConstraint(_identifier_check("product_id"), name="attempt_product_id_format"),
        CheckConstraint(_positive_integer_check("quantity"), name="quantity_bounds"),
        CheckConstraint(_non_negative_integer_check("amount_paise"), name="attempt_amount_bounds"),
        CheckConstraint("currency = 'INR'", name="attempt_currency_inr"),
        CheckConstraint(
            "status IN ('reserved', 'created', 'completed', 'retryable_failed', "
            "'failed', 'cancelled')",
            name="attempt_status_values",
        ),
        CheckConstraint(
            "(status IN ('reserved', 'created') AND reservation_expires_at IS NOT NULL) OR "
            "(status = 'retryable_failed') OR "
            "(status IN ('completed', 'failed', 'cancelled') "
            "AND reservation_expires_at IS NULL)",
            name="attempt_reservation_state",
        ),
        UniqueConstraint("idempotency_key", name="uq_checkout_attempts_idempotency_key"),
        UniqueConstraint(
            "mandate_id", "checkout_intent_id", name="uq_checkout_attempts_mandate_intent"
        ),
        ForeignKeyConstraint(
            [
                "mandate_id",
                "approval_id",
                "checkout_intent_id",
                "request_hash",
                "amount_paise",
                "currency",
            ],
            [
                "approvals.mandate_id",
                "approvals.approval_id",
                "approvals.checkout_intent_id",
                "approvals.request_hash",
                "approvals.amount_paise",
                "approvals.currency",
            ],
            name="fk_checkout_attempts_exact_approval_binding",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_checkout_attempts_mandate_reservation",
            "mandate_id",
            "reservation_expires_at",
        ),
    )

    attempt_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    mandate_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("mandates.mandate_id", ondelete="RESTRICT"), nullable=False
    )
    checkout_intent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    product_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("products.product_id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    reservation_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    approval_id: Mapped[str | None] = mapped_column(String(128), nullable=True)


class AuditEventRecord(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(_identifier_check("event_id"), name="audit_event_id_format"),
        CheckConstraint(
            "mandate_id IS NULL OR (length(mandate_id) BETWEEN 1 AND 128)",
            name="audit_mandate_id_length",
        ),
        CheckConstraint(
            "request_id IS NULL OR (length(request_id) BETWEEN 1 AND 128)",
            name="audit_request_id_length",
        ),
        CheckConstraint(
            "tool_called IS NULL OR (length(tool_called) BETWEEN 1 AND 128)",
            name="audit_tool_length",
        ),
        CheckConstraint(
            "rule_invoked IN ('MG-001', 'MG-002', 'MG-003', 'MG-004', 'MG-005', "
            "'MG-006', 'MG-007', 'MG-008', 'MG-009', 'MG-010', 'MG-011')",
            name="audit_rule_values",
        ),
        CheckConstraint(
            "decision IN ('allow', 'block', 'request_approval')", name="audit_decision_values"
        ),
        CheckConstraint(
            "execution_mode IN ('execute', 'replay', 'retry_existing', 'none')",
            name="audit_execution_mode_values",
        ),
        CheckConstraint(_hash_check("fingerprint"), name="audit_fingerprint_format"),
        CheckConstraint(
            "json_valid(arguments_json) = 1 AND json_type(arguments_json) = 'object'",
            name="audit_arguments_json_object",
        ),
        CheckConstraint(
            "json_valid(evidence_json) = 1 AND json_type(evidence_json) = 'array'",
            name="audit_evidence_json_array",
        ),
        CheckConstraint(
            "json_valid(request_envelope_json) = 1 AND json_type(request_envelope_json) = 'object'",
            name="audit_request_envelope_json_object",
        ),
        Index("ix_audit_events_mandate_time", "mandate_id", "evaluated_at", "event_id"),
    )

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    mandate_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tool_called: Mapped[str | None] = mapped_column(String(128), nullable=True)
    arguments_json: Mapped[str] = mapped_column(Text, nullable=False)
    request_envelope_json: Mapped[str] = mapped_column(Text, nullable=False)
    rule_invoked: Mapped[str] = mapped_column(String(8), nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(24), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    effect_approval_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("approvals.approval_id", ondelete="RESTRICT"), nullable=True
    )
    effect_attempt_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("checkout_attempts.attempt_id", ondelete="RESTRICT"), nullable=True
    )


class ApprovalDecisionEventRecord(Base):
    """Append-only record of an authenticated human approval decision."""

    __tablename__ = "approval_decision_events"
    __table_args__ = (
        CheckConstraint(_identifier_check("event_id"), name="approval_decision_event_id_format"),
        CheckConstraint(
            _identifier_check("approval_id"), name="approval_decision_approval_id_format"
        ),
        CheckConstraint(
            _identifier_check("mandate_id"), name="approval_decision_mandate_id_format"
        ),
        CheckConstraint(
            _identifier_check("checkout_intent_id"), name="approval_decision_intent_id_format"
        ),
        CheckConstraint(_hash_check("request_hash"), name="approval_decision_hash_format"),
        CheckConstraint(
            _non_negative_integer_check("amount_paise"), name="approval_decision_amount_bounds"
        ),
        CheckConstraint("currency = 'INR'", name="approval_decision_currency_inr"),
        CheckConstraint(
            "requested_decision IN ('grant', 'reject')",
            name="approval_decision_action_values",
        ),
        CheckConstraint(
            "resulting_status IN ('granted', 'rejected')",
            name="approval_decision_status_values",
        ),
        CheckConstraint("actor_type = 'trusted_human'", name="approval_decision_actor_type"),
        CheckConstraint(
            "typeof(replayed) = 'integer' AND replayed IN (0, 1)",
            name="approval_decision_replayed_boolean",
        ),
        ForeignKeyConstraint(
            [
                "mandate_id",
                "approval_id",
                "checkout_intent_id",
                "request_hash",
                "amount_paise",
                "currency",
            ],
            [
                "approvals.mandate_id",
                "approvals.approval_id",
                "approvals.checkout_intent_id",
                "approvals.request_hash",
                "approvals.amount_paise",
                "approvals.currency",
            ],
            name="fk_approval_decision_events_exact_binding",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_approval_decision_events_approval_time",
            "approval_id",
            "evaluated_at",
            "event_id",
        ),
    )

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    approval_id: Mapped[str] = mapped_column(String(128), nullable=False)
    mandate_id: Mapped[str] = mapped_column(String(128), nullable=False)
    checkout_intent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    requested_decision: Mapped[str] = mapped_column(String(8), nullable=False)
    resulting_status: Mapped[str] = mapped_column(String(16), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    replayed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
