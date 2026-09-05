"""Idempotently seed the explicitly synthetic MandateGuard demo catalog."""

from datetime import datetime, timedelta

from mandateguard.core.config import get_settings
from mandateguard.core.time import normalize_utc, utc_now
from mandateguard.db.repositories import MandateRepository, ProductRepository
from mandateguard.db.session import SessionFactory, create_database_engine, create_session_factory
from mandateguard.domain import Mandate, Product
from mandateguard.domain.enums import MandateStatus

DEMO_MANDATE_ID = "mandate-demo"
DEMO_DATA_VALIDITY = timedelta(days=365)


def demo_mandate(*, seeded_at: datetime) -> Mandate:
    return Mandate(
        mandate_id=DEMO_MANDATE_ID,
        status=MandateStatus.ACTIVE,
        currency="INR",
        total_budget_paise=600_000,
        per_item_cap_paise=250_000,
        approval_threshold_paise=200_000,
        approved_merchants=frozenset({"lumin", "audion", "ergoworks"}),
        approved_categories=frozenset({"home", "electronics", "furniture"}),
        expires_at=seeded_at + DEMO_DATA_VALIDITY,
    )


def demo_products(*, seeded_at: datetime) -> tuple[Product, ...]:
    expiry = seeded_at + DEMO_DATA_VALIDITY
    return (
        Product(
            product_id="desk-lamp",
            merchant_id="lumin",
            category_id="home",
            currency="INR",
            unit_price_paise=129_900,
            inventory_count=12,
            price_version=3,
            inventory_version=8,
            active=True,
            offer_expires_at=expiry,
        ),
        Product(
            product_id="noise-cancelling-headphones",
            merchant_id="audion",
            category_id="electronics",
            currency="INR",
            unit_price_paise=249_900,
            inventory_count=7,
            price_version=5,
            inventory_version=11,
            active=True,
            offer_expires_at=expiry,
        ),
        Product(
            product_id="ergonomic-chair",
            merchant_id="ergoworks",
            category_id="furniture",
            currency="INR",
            unit_price_paise=279_900,
            inventory_count=4,
            price_version=2,
            inventory_version=6,
            active=True,
            offer_expires_at=expiry,
        ),
        Product(
            product_id="travel-backpack",
            merchant_id="untrusted-shop",
            category_id="home",
            currency="INR",
            unit_price_paise=189_900,
            inventory_count=20,
            price_version=1,
            inventory_version=2,
            active=True,
            offer_expires_at=expiry,
        ),
    )


def seed_demo_data(session_factory: SessionFactory, *, seeded_at: datetime | None = None) -> None:
    timestamp = normalize_utc(seeded_at or utc_now())
    with session_factory.begin() as session:
        mandates = MandateRepository(session)
        products = ProductRepository(session)
        if mandates.get(DEMO_MANDATE_ID) is None:
            mandates.add(demo_mandate(seeded_at=timestamp))
        for product in demo_products(seeded_at=timestamp):
            if products.get(product.product_id) is None:
                products.add(product)


def main() -> None:
    settings = get_settings()
    engine = create_database_engine(settings.database_url)
    try:
        seed_demo_data(create_session_factory(engine))
    finally:
        engine.dispose()
    print("Seeded synthetic demo mandate and 4 products.")


if __name__ == "__main__":
    main()
