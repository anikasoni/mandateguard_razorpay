"""Add Phase 2B policy persistence.

Revision ID: 20260830_01
Revises:
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from mandateguard.db.types import UTCDateTime

revision: str = "20260830_01"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MAX_DB_INTEGER = 2**63 - 1


def _identifier(column: str, limit: int = 128) -> str:
    return (
        f"length({column}) BETWEEN 1 AND {limit} "
        f"AND substr({column}, 1, 1) GLOB '[A-Za-z0-9]' "
        f"AND {column} NOT GLOB '*[^A-Za-z0-9_.:-]*'"
    )


def _canonical_id(column: str) -> str:
    return (
        f"length({column}) BETWEEN 1 AND 64 "
        f"AND substr({column}, 1, 1) GLOB '[a-z0-9]' "
        f"AND {column} NOT GLOB '*[^a-z0-9_-]*'"
    )


def _hash(column: str) -> str:
    return f"length({column}) = 64 AND {column} NOT GLOB '*[^0-9a-f]*'"


def _integer(column: str, minimum: int) -> str:
    return f"typeof({column}) = 'integer' AND {column} BETWEEN {minimum} AND {MAX_DB_INTEGER}"


def upgrade() -> None:
    """Create policy state and append-only audit storage."""

    op.create_table(
        "mandates",
        sa.Column("mandate_id", sa.String(128), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("total_budget_paise", sa.Integer(), nullable=False),
        sa.Column("per_item_cap_paise", sa.Integer(), nullable=False),
        sa.Column("approval_threshold_paise", sa.Integer(), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint(_identifier("mandate_id"), name="mandate_id_format"),
        sa.CheckConstraint(
            "status IN ('active', 'revoked', 'fulfilled')", name="mandate_status_values"
        ),
        sa.CheckConstraint("currency = 'INR'", name="mandate_currency_inr"),
        sa.CheckConstraint(_integer("total_budget_paise", 0), name="total_budget_bounds"),
        sa.CheckConstraint(_integer("per_item_cap_paise", 0), name="per_item_cap_bounds"),
        sa.CheckConstraint(
            _integer("approval_threshold_paise", 0), name="approval_threshold_bounds"
        ),
    )
    op.create_table(
        "mandate_merchant_scopes",
        sa.Column("mandate_id", sa.String(128), primary_key=True),
        sa.Column("merchant_id", sa.String(64), primary_key=True),
        sa.CheckConstraint(_canonical_id("merchant_id"), name="merchant_id_format"),
        sa.ForeignKeyConstraint(["mandate_id"], ["mandates.mandate_id"], ondelete="CASCADE"),
    )
    op.create_table(
        "mandate_category_scopes",
        sa.Column("mandate_id", sa.String(128), primary_key=True),
        sa.Column("category_id", sa.String(64), primary_key=True),
        sa.CheckConstraint(_canonical_id("category_id"), name="category_id_format"),
        sa.ForeignKeyConstraint(["mandate_id"], ["mandates.mandate_id"], ondelete="CASCADE"),
    )
    op.create_table(
        "products",
        sa.Column("product_id", sa.String(128), primary_key=True),
        sa.Column("merchant_id", sa.String(64), nullable=False),
        sa.Column("category_id", sa.String(64), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("unit_price_paise", sa.Integer(), nullable=False),
        sa.Column("inventory_count", sa.Integer(), nullable=False),
        sa.Column("price_version", sa.Integer(), nullable=False),
        sa.Column("inventory_version", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("offer_expires_at", UTCDateTime(), nullable=True),
        sa.CheckConstraint(_identifier("product_id"), name="product_id_format"),
        sa.CheckConstraint(_canonical_id("merchant_id"), name="product_merchant_format"),
        sa.CheckConstraint(_canonical_id("category_id"), name="product_category_format"),
        sa.CheckConstraint("currency = 'INR'", name="product_currency_inr"),
        sa.CheckConstraint(_integer("unit_price_paise", 0), name="unit_price_bounds"),
        sa.CheckConstraint(_integer("inventory_count", 0), name="inventory_count_bounds"),
        sa.CheckConstraint(_integer("price_version", 0), name="price_version_bounds"),
        sa.CheckConstraint(_integer("inventory_version", 0), name="inventory_version_bounds"),
        sa.CheckConstraint(
            "typeof(active) = 'integer' AND active IN (0, 1)", name="active_boolean"
        ),
    )
    op.create_table(
        "approvals",
        sa.Column("approval_id", sa.String(128), primary_key=True),
        sa.Column("mandate_id", sa.String(128), nullable=False),
        sa.Column("checkout_intent_id", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("live_binding", sa.Integer(), nullable=False),
        sa.CheckConstraint(_identifier("approval_id"), name="approval_id_format"),
        sa.CheckConstraint(_identifier("checkout_intent_id"), name="approval_intent_format"),
        sa.CheckConstraint(_hash("request_hash"), name="approval_request_hash_format"),
        sa.CheckConstraint(_integer("amount_paise", 0), name="approval_amount_bounds"),
        sa.CheckConstraint("currency = 'INR'", name="approval_currency_inr"),
        sa.CheckConstraint(
            "status IN ('pending', 'granted', 'rejected', 'revoked', 'consumed')",
            name="approval_status_values",
        ),
        sa.CheckConstraint(
            "typeof(live_binding) = 'integer' AND live_binding IN (0, 1)",
            name="approval_live_binding_boolean",
        ),
        sa.CheckConstraint(
            "live_binding = 0 OR status IN ('pending', 'granted')",
            name="live_binding_requires_live_status",
        ),
        sa.ForeignKeyConstraint(["mandate_id"], ["mandates.mandate_id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "mandate_id",
            "approval_id",
            "checkout_intent_id",
            "request_hash",
            "amount_paise",
            "currency",
            name="uq_approvals_exact_binding",
        ),
    )
    op.create_index(
        "ix_approvals_mandate_intent", "approvals", ["mandate_id", "checkout_intent_id"]
    )
    op.create_index(
        "uq_approvals_live_binding",
        "approvals",
        ["mandate_id", "checkout_intent_id", "request_hash", "amount_paise", "currency"],
        unique=True,
        sqlite_where=sa.text("live_binding = 1 AND status IN ('pending', 'granted')"),
    )
    op.create_table(
        "checkout_attempts",
        sa.Column("attempt_id", sa.String(128), primary_key=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("mandate_id", sa.String(128), nullable=False),
        sa.Column("checkout_intent_id", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("product_id", sa.String(128), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("reservation_expires_at", UTCDateTime(), nullable=True),
        sa.Column("approval_id", sa.String(128), nullable=True),
        sa.CheckConstraint(_identifier("attempt_id"), name="attempt_id_format"),
        sa.CheckConstraint(_identifier("idempotency_key"), name="idempotency_key_format"),
        sa.CheckConstraint(_identifier("checkout_intent_id"), name="attempt_intent_format"),
        sa.CheckConstraint(_hash("request_hash"), name="attempt_request_hash_format"),
        sa.CheckConstraint(_identifier("product_id"), name="attempt_product_id_format"),
        sa.CheckConstraint(_integer("quantity", 1), name="quantity_bounds"),
        sa.CheckConstraint(_integer("amount_paise", 0), name="attempt_amount_bounds"),
        sa.CheckConstraint("currency = 'INR'", name="attempt_currency_inr"),
        sa.CheckConstraint(
            "status IN ('reserved', 'created', 'completed', 'retryable_failed', "
            "'failed', 'cancelled')",
            name="attempt_status_values",
        ),
        sa.CheckConstraint(
            "(status IN ('reserved', 'created') AND reservation_expires_at IS NOT NULL) OR "
            "(status = 'retryable_failed') OR "
            "(status IN ('completed', 'failed', 'cancelled') "
            "AND reservation_expires_at IS NULL)",
            name="attempt_reservation_state",
        ),
        sa.ForeignKeyConstraint(["mandate_id"], ["mandates.mandate_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["products.product_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
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
        sa.UniqueConstraint("idempotency_key", name="uq_checkout_attempts_idempotency_key"),
        sa.UniqueConstraint(
            "mandate_id", "checkout_intent_id", name="uq_checkout_attempts_mandate_intent"
        ),
    )
    op.create_index(
        "ix_checkout_attempts_mandate_reservation",
        "checkout_attempts",
        ["mandate_id", "reservation_expires_at"],
    )
    op.create_table(
        "audit_events",
        sa.Column("event_id", sa.String(128), primary_key=True),
        sa.Column("mandate_id", sa.String(128), nullable=True),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("tool_called", sa.String(128), nullable=True),
        sa.Column("arguments_json", sa.Text(), nullable=False),
        sa.Column("request_envelope_json", sa.Text(), nullable=False),
        sa.Column("rule_invoked", sa.String(8), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("decision", sa.String(24), nullable=False),
        sa.Column("execution_mode", sa.String(24), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evaluated_at", UTCDateTime(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("effect_approval_id", sa.String(128), nullable=True),
        sa.Column("effect_attempt_id", sa.String(128), nullable=True),
        sa.CheckConstraint(_identifier("event_id"), name="audit_event_id_format"),
        sa.CheckConstraint(
            "mandate_id IS NULL OR length(mandate_id) BETWEEN 1 AND 128",
            name="audit_mandate_id_length",
        ),
        sa.CheckConstraint(
            "request_id IS NULL OR length(request_id) BETWEEN 1 AND 128",
            name="audit_request_id_length",
        ),
        sa.CheckConstraint(
            "tool_called IS NULL OR length(tool_called) BETWEEN 1 AND 128",
            name="audit_tool_length",
        ),
        sa.CheckConstraint(
            "rule_invoked IN ('MG-001', 'MG-002', 'MG-003', 'MG-004', 'MG-005', "
            "'MG-006', 'MG-007', 'MG-008', 'MG-009', 'MG-010', 'MG-011')",
            name="audit_rule_values",
        ),
        sa.CheckConstraint(
            "decision IN ('allow', 'block', 'request_approval')", name="audit_decision_values"
        ),
        sa.CheckConstraint(
            "execution_mode IN ('execute', 'replay', 'retry_existing', 'none')",
            name="audit_execution_mode_values",
        ),
        sa.CheckConstraint(_hash("fingerprint"), name="audit_fingerprint_format"),
        sa.CheckConstraint(
            "json_valid(arguments_json) = 1 AND json_type(arguments_json) = 'object'",
            name="audit_arguments_json_object",
        ),
        sa.CheckConstraint(
            "json_valid(evidence_json) = 1 AND json_type(evidence_json) = 'array'",
            name="audit_evidence_json_array",
        ),
        sa.CheckConstraint(
            "json_valid(request_envelope_json) = 1 AND json_type(request_envelope_json) = 'object'",
            name="audit_request_envelope_json_object",
        ),
        sa.ForeignKeyConstraint(
            ["effect_approval_id"], ["approvals.approval_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["effect_attempt_id"], ["checkout_attempts.attempt_id"], ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "ix_audit_events_mandate_time",
        "audit_events",
        ["mandate_id", "evaluated_at", "event_id"],
    )
    op.execute(
        "CREATE TRIGGER trg_audit_events_no_update "
        "BEFORE UPDATE ON audit_events BEGIN "
        "SELECT RAISE(ABORT, 'audit_events are append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER trg_audit_events_no_delete "
        "BEFORE DELETE ON audit_events BEGIN "
        "SELECT RAISE(ABORT, 'audit_events are append-only'); END"
    )


def downgrade() -> None:
    """Remove policy persistence in dependency order."""

    op.execute("DROP TRIGGER IF EXISTS trg_audit_events_no_delete")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_events_no_update")
    op.drop_index("ix_audit_events_mandate_time", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_checkout_attempts_mandate_reservation", table_name="checkout_attempts")
    op.drop_table("checkout_attempts")
    op.drop_index("uq_approvals_live_binding", table_name="approvals")
    op.drop_index("ix_approvals_mandate_intent", table_name="approvals")
    op.drop_table("approvals")
    op.drop_table("products")
    op.drop_table("mandate_category_scopes")
    op.drop_table("mandate_merchant_scopes")
    op.drop_table("mandates")
