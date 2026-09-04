"""Add append-only human approval decision events.

Revision ID: 20260904_02
Revises: 20260830_01
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from mandateguard.db.types import UTCDateTime

revision: str = "20260904_02"
down_revision: str | Sequence[str] | None = "20260830_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MAX_DB_INTEGER = 2**63 - 1


def _identifier(column: str) -> str:
    return (
        f"length({column}) BETWEEN 1 AND 128 "
        f"AND substr({column}, 1, 1) GLOB '[A-Za-z0-9]' "
        f"AND {column} NOT GLOB '*[^A-Za-z0-9_.:-]*'"
    )


def upgrade() -> None:
    op.create_table(
        "approval_decision_events",
        sa.Column("event_id", sa.String(128), primary_key=True),
        sa.Column("approval_id", sa.String(128), nullable=False),
        sa.Column("mandate_id", sa.String(128), nullable=False),
        sa.Column("checkout_intent_id", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("requested_decision", sa.String(8), nullable=False),
        sa.Column("resulting_status", sa.String(16), nullable=False),
        sa.Column("evaluated_at", UTCDateTime(), nullable=False),
        sa.Column("replayed", sa.Boolean(), nullable=False),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.CheckConstraint(_identifier("event_id"), name="approval_decision_event_id_format"),
        sa.CheckConstraint(_identifier("approval_id"), name="approval_decision_approval_id_format"),
        sa.CheckConstraint(_identifier("mandate_id"), name="approval_decision_mandate_id_format"),
        sa.CheckConstraint(
            _identifier("checkout_intent_id"), name="approval_decision_intent_id_format"
        ),
        sa.CheckConstraint(
            "length(request_hash) = 64 AND request_hash NOT GLOB '*[^0-9a-f]*'",
            name="approval_decision_hash_format",
        ),
        sa.CheckConstraint(
            f"typeof(amount_paise) = 'integer' AND amount_paise BETWEEN 0 AND {MAX_DB_INTEGER}",
            name="approval_decision_amount_bounds",
        ),
        sa.CheckConstraint("currency = 'INR'", name="approval_decision_currency_inr"),
        sa.CheckConstraint(
            "requested_decision IN ('grant', 'reject')",
            name="approval_decision_action_values",
        ),
        sa.CheckConstraint(
            "resulting_status IN ('granted', 'rejected')",
            name="approval_decision_status_values",
        ),
        sa.CheckConstraint("actor_type = 'trusted_human'", name="approval_decision_actor_type"),
        sa.CheckConstraint(
            "typeof(replayed) = 'integer' AND replayed IN (0, 1)",
            name="approval_decision_replayed_boolean",
        ),
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
            name="fk_approval_decision_events_exact_binding",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_approval_decision_events_approval_time",
        "approval_decision_events",
        ["approval_id", "evaluated_at", "event_id"],
    )
    op.execute(
        "CREATE TRIGGER trg_approval_decision_events_no_update "
        "BEFORE UPDATE ON approval_decision_events BEGIN "
        "SELECT RAISE(ABORT, 'approval_decision_events are append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER trg_approval_decision_events_no_delete "
        "BEFORE DELETE ON approval_decision_events BEGIN "
        "SELECT RAISE(ABORT, 'approval_decision_events are append-only'); END"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_approval_decision_events_no_delete")
    op.execute("DROP TRIGGER IF EXISTS trg_approval_decision_events_no_update")
    op.drop_index(
        "ix_approval_decision_events_approval_time",
        table_name="approval_decision_events",
    )
    op.drop_table("approval_decision_events")
