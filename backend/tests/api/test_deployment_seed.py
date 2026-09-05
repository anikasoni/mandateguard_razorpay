"""Deployment seed restart behavior."""

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from mandateguard.db.models import (
    ApprovalRecord,
    AuditEventRecord,
    CheckoutAttemptRecord,
    MandateRecord,
    PaymentOrderRecord,
    ProductRecord,
)
from mandateguard.demo.seed import seed_demo_data


def test_demo_seed_is_idempotent_and_creates_no_transactional_fixtures(
    api_client: TestClient,
) -> None:
    factory = api_client.app.state.database_session_factory

    seed_demo_data(factory)
    seed_demo_data(factory)

    with factory() as session:
        mandate_count = session.scalar(
            select(func.count())
            .select_from(MandateRecord)
            .where(MandateRecord.mandate_id == "mandate-demo")
        )
        product_count = session.scalar(
            select(func.count())
            .select_from(ProductRecord)
            .where(
                ProductRecord.product_id.in_(
                    (
                        "desk-lamp",
                        "noise-cancelling-headphones",
                        "ergonomic-chair",
                        "travel-backpack",
                    )
                )
            )
        )
        transactional_counts = tuple(
            session.scalar(select(func.count()).select_from(model)) or 0
            for model in (
                ApprovalRecord,
                CheckoutAttemptRecord,
                PaymentOrderRecord,
                AuditEventRecord,
            )
        )

    assert (mandate_count, product_count) == (1, 4)
    assert transactional_counts == (0, 0, 0, 0)
