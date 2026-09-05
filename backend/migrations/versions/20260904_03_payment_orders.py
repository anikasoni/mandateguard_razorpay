"""Add idempotent payment order bindings.

Revision ID: 20260904_03
Revises: 20260904_02
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from mandateguard.db.types import UTCDateTime

revision: str = "20260904_03"
down_revision: str | Sequence[str] | None = "20260904_02"
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
        "payment_orders",
        sa.Column("provider_order_id", sa.String(128), primary_key=True),
        sa.Column("attempt_id", sa.String(128), nullable=False),
        sa.Column("receipt", sa.String(128), nullable=False),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("provider_mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("provider_payment_id", sa.String(128), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("paid_at", UTCDateTime(), nullable=True),
        sa.CheckConstraint(_identifier("provider_order_id"), name="payment_order_id_format"),
        sa.CheckConstraint(_identifier("attempt_id"), name="payment_order_attempt_id_format"),
        sa.CheckConstraint(_identifier("receipt"), name="payment_order_receipt_format"),
        sa.CheckConstraint(
            f"typeof(amount_paise) = 'integer' AND amount_paise BETWEEN 0 AND {MAX_DB_INTEGER}",
            name="payment_order_amount",
        ),
        sa.CheckConstraint("currency = 'INR'", name="payment_order_currency_inr"),
        sa.CheckConstraint(
            "provider_mode IN ('razorpay_test', 'simulated')", name="payment_order_mode"
        ),
        sa.CheckConstraint("status IN ('created', 'paid')", name="payment_order_status"),
        sa.CheckConstraint(
            "(status = 'created' AND provider_payment_id IS NULL AND paid_at IS NULL) OR "
            "(status = 'paid' AND provider_mode = 'razorpay_test' "
            "AND provider_payment_id IS NOT NULL AND paid_at IS NOT NULL)",
            name="payment_order_state",
        ),
        sa.CheckConstraint(
            f"provider_payment_id IS NULL OR ({_identifier('provider_payment_id')})",
            name="payment_order_payment_id_format",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["checkout_attempts.attempt_id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("attempt_id", name="uq_payment_orders_attempt"),
        sa.UniqueConstraint("receipt", name="uq_payment_orders_receipt"),
        sa.UniqueConstraint("provider_payment_id", name="uq_payment_orders_payment"),
    )


def downgrade() -> None:
    op.drop_table("payment_orders")
