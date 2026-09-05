"""Deployment seed restart behavior."""

from datetime import UTC, datetime, timedelta

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
from mandateguard.demo.seed import DEMO_DATA_VALIDITY, seed_demo_data


def test_demo_seed_is_idempotent_and_creates_no_transactional_fixtures(
    api_client: TestClient,
) -> None:
    factory = api_client.app.state.database_session_factory
    first_start = datetime(2042, 3, 10, 9, 30, tzinfo=UTC)

    seed_demo_data(factory, seeded_at=first_start)
    seed_demo_data(factory, seeded_at=first_start + timedelta(hours=1))

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
        stored_mandate = session.get(MandateRecord, "mandate-demo")
        stored_products = session.scalars(
            select(ProductRecord).where(
                ProductRecord.product_id.in_(
                    (
                        "desk-lamp",
                        "noise-cancelling-headphones",
                        "ergonomic-chair",
                        "travel-backpack",
                    )
                )
            )
        ).all()

    assert (mandate_count, product_count) == (1, 4)
    assert transactional_counts == (0, 0, 0, 0)
    assert stored_mandate is not None
    assert stored_mandate.status == "active"
    assert stored_mandate.expires_at == first_start + DEMO_DATA_VALIDITY
    assert all(
        product.offer_expires_at == first_start + DEMO_DATA_VALIDITY for product in stored_products
    )
