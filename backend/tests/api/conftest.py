"""Alembic-created API integration fixtures."""

from collections.abc import Callable, Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from mandateguard.core.config import Settings, get_settings
from mandateguard.db.repositories import MandateRepository, ProductRepository
from mandateguard.db.session import create_database_engine, create_session_factory
from mandateguard.domain import Mandate, Product
from mandateguard.main import create_app

NOW = datetime(2026, 9, 4, 12, tzinfo=UTC)
HUMAN_KEY = "local-human-key-for-tests"


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def api_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[TestClient, None, None]:
    database_path = tmp_path / "policy-api.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("MANDATEGUARD_DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config("backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")

    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    mandate = Mandate(
        mandate_id="mandate-1",
        status="active",
        currency="INR",
        total_budget_paise=100_000,
        per_item_cap_paise=20_000,
        approval_threshold_paise=10_000,
        approved_merchants={"acme"},
        approved_categories={"office"},
        expires_at=NOW + timedelta(days=1),
    )
    product = Product(
        product_id="product-1",
        merchant_id="acme",
        category_id="office",
        currency="INR",
        unit_price_paise=5_000,
        inventory_count=20,
        price_version=7,
        inventory_version=4,
        active=True,
        offer_expires_at=NOW + timedelta(hours=1),
    )
    with factory.begin() as session:
        MandateRepository(session).add(mandate)
        ProductRepository(session).add(product)
    engine.dispose()

    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        human_approval_key=HUMAN_KEY,
        cors_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    )
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture
def request_factory() -> Callable[..., dict[str, Any]]:
    def build(tool: str, **changes: Any) -> dict[str, Any]:
        if tool == "get_product":
            arguments: dict[str, Any] = {"product_id": "product-1", "currency": "INR"}
        else:
            arguments = {
                "product_id": "product-1",
                "checkout_intent_id": f"intent-{tool}",
                "quantity": 2,
                "currency": "INR",
                "quoted_unit_price_paise": 5_000,
                "price_version": 7,
                "inventory_version": 4,
            }
            if tool == "present_offer":
                arguments["claims"] = {}
            else:
                arguments["approval_id"] = None
        arguments.update(changes)
        return {
            "request_id": f"request-{tool}",
            "mandate_id": "mandate-1",
            "tool": tool,
            "arguments": arguments,
        }

    return build
