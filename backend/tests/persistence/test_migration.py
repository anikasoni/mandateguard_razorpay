"""Alembic Phase 2B migration tests against the schema Alembic actually creates."""

from collections.abc import Generator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect
from sqlalchemy.exc import IntegrityError

from mandateguard.core.config import get_settings
from mandateguard.db.session import create_database_engine

EXPECTED_TABLES = {
    "alembic_version",
    "mandates",
    "mandate_merchant_scopes",
    "mandate_category_scopes",
    "products",
    "approvals",
    "checkout_attempts",
    "audit_events",
    "approval_decision_events",
    "payment_orders",
}
EXPECTED_COLUMNS: dict[str, dict[str, bool]] = {
    "mandates": {
        "mandate_id": False,
        "status": False,
        "currency": False,
        "total_budget_paise": False,
        "per_item_cap_paise": False,
        "approval_threshold_paise": False,
        "expires_at": False,
    },
    "mandate_merchant_scopes": {"mandate_id": False, "merchant_id": False},
    "mandate_category_scopes": {"mandate_id": False, "category_id": False},
    "products": {
        "product_id": False,
        "merchant_id": False,
        "category_id": False,
        "currency": False,
        "unit_price_paise": False,
        "inventory_count": False,
        "price_version": False,
        "inventory_version": False,
        "active": False,
        "offer_expires_at": True,
    },
    "approvals": {
        "approval_id": False,
        "mandate_id": False,
        "checkout_intent_id": False,
        "request_hash": False,
        "amount_paise": False,
        "currency": False,
        "status": False,
        "expires_at": False,
        "live_binding": False,
    },
    "checkout_attempts": {
        "attempt_id": False,
        "idempotency_key": False,
        "mandate_id": False,
        "checkout_intent_id": False,
        "request_hash": False,
        "product_id": False,
        "quantity": False,
        "amount_paise": False,
        "currency": False,
        "status": False,
        "reservation_expires_at": True,
        "approval_id": True,
    },
    "audit_events": {
        "event_id": False,
        "mandate_id": True,
        "request_id": True,
        "tool_called": True,
        "arguments_json": False,
        "request_envelope_json": False,
        "rule_invoked": False,
        "evidence_json": False,
        "decision": False,
        "execution_mode": False,
        "policy_version": False,
        "reason": False,
        "evaluated_at": False,
        "fingerprint": False,
        "effect_approval_id": True,
        "effect_attempt_id": True,
    },
    "approval_decision_events": {
        "event_id": False,
        "approval_id": False,
        "mandate_id": False,
        "checkout_intent_id": False,
        "request_hash": False,
        "amount_paise": False,
        "currency": False,
        "requested_decision": False,
        "resulting_status": False,
        "evaluated_at": False,
        "replayed": False,
        "actor_type": False,
    },
    "payment_orders": {
        "provider_order_id": False,
        "attempt_id": False,
        "receipt": False,
        "amount_paise": False,
        "currency": False,
        "provider_mode": False,
        "status": False,
        "provider_payment_id": True,
        "created_at": False,
        "paid_at": True,
    },
}
EXPECTED_CHECKS = {
    "mandates": {
        "mandate_id_format",
        "mandate_status_values",
        "mandate_currency_inr",
        "total_budget_bounds",
        "per_item_cap_bounds",
        "approval_threshold_bounds",
    },
    "mandate_merchant_scopes": {"merchant_id_format"},
    "mandate_category_scopes": {"category_id_format"},
    "products": {
        "product_id_format",
        "product_merchant_format",
        "product_category_format",
        "product_currency_inr",
        "unit_price_bounds",
        "inventory_count_bounds",
        "price_version_bounds",
        "inventory_version_bounds",
        "active_boolean",
    },
    "approvals": {
        "approval_id_format",
        "approval_intent_format",
        "approval_request_hash_format",
        "approval_amount_bounds",
        "approval_currency_inr",
        "approval_status_values",
        "approval_live_binding_boolean",
        "live_binding_requires_live_status",
    },
    "checkout_attempts": {
        "attempt_id_format",
        "idempotency_key_format",
        "attempt_intent_format",
        "attempt_request_hash_format",
        "attempt_product_id_format",
        "quantity_bounds",
        "attempt_amount_bounds",
        "attempt_currency_inr",
        "attempt_status_values",
        "attempt_reservation_state",
    },
    "audit_events": {
        "audit_event_id_format",
        "audit_mandate_id_length",
        "audit_request_id_length",
        "audit_tool_length",
        "audit_rule_values",
        "audit_decision_values",
        "audit_execution_mode_values",
        "audit_fingerprint_format",
        "audit_arguments_json_object",
        "audit_evidence_json_array",
        "audit_request_envelope_json_object",
    },
    "approval_decision_events": {
        "approval_decision_event_id_format",
        "approval_decision_approval_id_format",
        "approval_decision_mandate_id_format",
        "approval_decision_intent_id_format",
        "approval_decision_hash_format",
        "approval_decision_amount_bounds",
        "approval_decision_currency_inr",
        "approval_decision_action_values",
        "approval_decision_status_values",
        "approval_decision_actor_type",
        "approval_decision_replayed_boolean",
    },
    "payment_orders": {
        "payment_order_id_format",
        "payment_order_attempt_id_format",
        "payment_order_receipt_format",
        "payment_order_amount",
        "payment_order_currency_inr",
        "payment_order_mode",
        "payment_order_status",
        "payment_order_state",
        "payment_order_payment_id_format",
    },
}
EXPECTED_UNIQUES = {
    "approvals": {"uq_approvals_exact_binding"},
    "checkout_attempts": {
        "uq_checkout_attempts_idempotency_key",
        "uq_checkout_attempts_mandate_intent",
    },
    "payment_orders": {
        "uq_payment_orders_attempt",
        "uq_payment_orders_receipt",
        "uq_payment_orders_payment",
    },
}
EXPECTED_INDEXES = {
    "approvals": {"ix_approvals_mandate_intent", "uq_approvals_live_binding"},
    "checkout_attempts": {"ix_checkout_attempts_mandate_reservation"},
    "audit_events": {"ix_audit_events_mandate_time"},
    "approval_decision_events": {"ix_approval_decision_events_approval_time"},
}


def _config(database_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("MANDATEGUARD_DATABASE_URL", url)
    get_settings.cache_clear()
    config = Config("backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    return config


@pytest.fixture
def migrated_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[tuple[Engine, Config], None, None]:
    database_path = tmp_path / "alembic-created.db"
    config = _config(database_path, monkeypatch)
    command.upgrade(config, "head")
    engine = create_database_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    try:
        yield engine, config
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_alembic_created_schema_has_exact_columns_constraints_and_indexes(
    migrated_database: tuple[Engine, Config],
) -> None:
    engine, _ = migrated_database
    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == EXPECTED_TABLES

    for table, expected_columns in EXPECTED_COLUMNS.items():
        actual_columns = {
            column["name"]: column["nullable"] for column in inspector.get_columns(table)
        }
        assert actual_columns == expected_columns
        assert {item["name"] for item in inspector.get_check_constraints(table)} == {
            f"ck_{table}_{name}" for name in EXPECTED_CHECKS[table]
        }
        assert {item["name"] for item in inspector.get_unique_constraints(table)} == (
            EXPECTED_UNIQUES.get(table, set())
        )
        assert {item["name"] for item in inspector.get_indexes(table)} == (
            EXPECTED_INDEXES.get(table, set())
        )

    approval_index = next(
        item
        for item in inspector.get_indexes("approvals")
        if item["name"] == "uq_approvals_live_binding"
    )
    assert approval_index["unique"] == 1
    assert str(approval_index["dialect_options"]["sqlite_where"]) == (
        "live_binding = 1 AND status IN ('pending', 'granted')"
    )


def test_alembic_created_schema_has_exact_foreign_keys_and_delete_actions(
    migrated_database: tuple[Engine, Config],
) -> None:
    engine, _ = migrated_database
    inspector = inspect(engine)

    def foreign_keys(table: str) -> set[tuple[tuple[str, ...], str, tuple[str, ...], str | None]]:
        return {
            (
                tuple(item["constrained_columns"]),
                item["referred_table"],
                tuple(item["referred_columns"]),
                item["options"].get("ondelete"),
            )
            for item in inspector.get_foreign_keys(table)
        }

    assert foreign_keys("mandate_merchant_scopes") == {
        (("mandate_id",), "mandates", ("mandate_id",), "CASCADE")
    }
    assert foreign_keys("mandate_category_scopes") == {
        (("mandate_id",), "mandates", ("mandate_id",), "CASCADE")
    }
    assert foreign_keys("approvals") == {(("mandate_id",), "mandates", ("mandate_id",), "RESTRICT")}
    assert foreign_keys("checkout_attempts") == {
        (("mandate_id",), "mandates", ("mandate_id",), "RESTRICT"),
        (("product_id",), "products", ("product_id",), "RESTRICT"),
        (
            (
                "mandate_id",
                "approval_id",
                "checkout_intent_id",
                "request_hash",
                "amount_paise",
                "currency",
            ),
            "approvals",
            (
                "mandate_id",
                "approval_id",
                "checkout_intent_id",
                "request_hash",
                "amount_paise",
                "currency",
            ),
            "RESTRICT",
        ),
    }
    assert foreign_keys("audit_events") == {
        (("effect_approval_id",), "approvals", ("approval_id",), "RESTRICT"),
        (("effect_attempt_id",), "checkout_attempts", ("attempt_id",), "RESTRICT"),
    }
    assert foreign_keys("approval_decision_events") == {
        (
            (
                "mandate_id",
                "approval_id",
                "checkout_intent_id",
                "request_hash",
                "amount_paise",
                "currency",
            ),
            "approvals",
            (
                "mandate_id",
                "approval_id",
                "checkout_intent_id",
                "request_hash",
                "amount_paise",
                "currency",
            ),
            "RESTRICT",
        )
    }
    assert foreign_keys("payment_orders") == {
        (("attempt_id",), "checkout_attempts", ("attempt_id",), "RESTRICT")
    }
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1


def _seed_raw_state(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO mandates VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("mandate-1", "active", "INR", 10, 20, 30, "2026-09-01 00:00:00"),
        )
        connection.exec_driver_sql(
            "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("product-1", "acme", "office", "INR", 5, 10, 1, 1, 1, None),
        )


def test_alembic_created_constraints_enforce_representation_not_new_policy(
    migrated_database: tuple[Engine, Config],
) -> None:
    engine, _ = migrated_database
    _seed_raw_state(engine)

    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.exec_driver_sql(
            "INSERT INTO mandates VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("mandate-usd", "active", "USD", 1, 1, 1, "2026-09-01 00:00:00"),
        )
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.exec_driver_sql(
            "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("product-float", "acme", "office", "INR", 1.5, 1, 1, 1, 1, None),
        )
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.exec_driver_sql(
            "INSERT INTO mandates VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("mandate-float", "active", "INR", 1.5, 1, 1, "2026-09-01 00:00:00"),
        )
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.exec_driver_sql(
            "INSERT INTO approvals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "approval-usd",
                "mandate-1",
                "intent-1",
                "0" * 64,
                5,
                "USD",
                "granted",
                "2026-09-01 00:00:00",
                1,
            ),
        )
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.exec_driver_sql(
            "INSERT INTO checkout_attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "attempt-usd",
                "idem-usd",
                "mandate-1",
                "intent-usd",
                "0" * 64,
                "product-1",
                1,
                5,
                "USD",
                "completed",
                None,
                None,
            ),
        )
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.exec_driver_sql(
            "INSERT INTO approvals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "approval-float",
                "mandate-1",
                "intent-float",
                "0" * 64,
                1.5,
                "INR",
                "pending",
                "2026-09-01 00:00:00",
                1,
            ),
        )
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.exec_driver_sql(
            "INSERT INTO checkout_attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "attempt-float",
                "idem-float",
                "mandate-1",
                "intent-float",
                "0" * 64,
                "product-1",
                1.5,
                5,
                "INR",
                "completed",
                None,
                None,
            ),
        )


def test_alembic_created_live_approval_partial_uniqueness_and_boolean_check(
    migrated_database: tuple[Engine, Config],
) -> None:
    engine, _ = migrated_database
    _seed_raw_state(engine)
    binding = ("mandate-1", "intent-live", "0" * 64, 5, "INR")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO approvals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "approval-live-1",
                *binding,
                "pending",
                "2026-09-01 00:00:00",
                1,
            ),
        )
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.exec_driver_sql(
            "INSERT INTO approvals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "approval-live-2",
                *binding,
                "granted",
                "2026-09-01 00:00:00",
                1,
            ),
        )
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO approvals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "approval-history",
                *binding,
                "rejected",
                "2026-08-01 00:00:00",
                0,
            ),
        )
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.exec_driver_sql(
            "INSERT INTO approvals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "approval-bad-boolean",
                "mandate-1",
                "intent-bad",
                "1" * 64,
                5,
                "INR",
                "pending",
                "2026-09-01 00:00:00",
                2,
            ),
        )
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.exec_driver_sql(
            "INSERT INTO approvals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "approval-terminal-live",
                "mandate-1",
                "intent-terminal",
                "2" * 64,
                5,
                "INR",
                "consumed",
                "2026-09-01 00:00:00",
                1,
            ),
        )


def test_nullable_exact_approval_binding_and_audit_history_restriction(
    migrated_database: tuple[Engine, Config],
) -> None:
    engine, _ = migrated_database
    _seed_raw_state(engine)
    request_hash = "0" * 64
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO approvals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "approval-1",
                "mandate-1",
                "intent-bound",
                request_hash,
                5,
                "INR",
                "granted",
                "2026-09-01 00:00:00",
                1,
            ),
        )
        connection.exec_driver_sql(
            "INSERT INTO checkout_attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "attempt-unbound",
                "idem-unbound",
                "mandate-1",
                "intent-unbound",
                request_hash,
                "product-1",
                1,
                5,
                "INR",
                "completed",
                None,
                None,
            ),
        )
        connection.exec_driver_sql(
            "INSERT INTO checkout_attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "attempt-bound",
                "idem-bound",
                "mandate-1",
                "intent-bound",
                request_hash,
                "product-1",
                1,
                5,
                "INR",
                "completed",
                None,
                "approval-1",
            ),
        )
        connection.exec_driver_sql(
            "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "audit-1",
                "mandate-1",
                "request-1",
                "create_checkout",
                "{}",
                "{}",
                "MG-011",
                "[]",
                "allow",
                "execute",
                "2A",
                "authorized",
                "2026-08-30 12:00:00",
                "1" * 64,
                None,
                "attempt-bound",
            ),
        )
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.exec_driver_sql(
            "UPDATE checkout_attempts SET amount_paise = 6 WHERE attempt_id = 'attempt-bound'"
        )
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.exec_driver_sql(
            "DELETE FROM checkout_attempts WHERE attempt_id = 'attempt-bound'"
        )
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.exec_driver_sql(
            "UPDATE audit_events SET reason = 'tampered' WHERE event_id = 'audit-1'"
        )
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.exec_driver_sql("DELETE FROM audit_events WHERE event_id = 'audit-1'")
    with engine.connect() as connection:
        assert (
            connection.exec_driver_sql(
                "SELECT reason FROM audit_events WHERE event_id = 'audit-1'"
            ).scalar_one()
            == "authorized"
        )


def test_migration_upgrade_downgrade_upgrade_round_trip(
    migrated_database: tuple[Engine, Config],
) -> None:
    engine, config = migrated_database
    engine.dispose()
    command.downgrade(config, "base")
    downgraded_engine = create_database_engine(config.get_main_option("sqlalchemy.url"))
    try:
        assert set(inspect(downgraded_engine).get_table_names()) == {"alembic_version"}
        with downgraded_engine.connect() as connection:
            assert (
                connection.exec_driver_sql(
                    "SELECT count(*) FROM sqlite_master WHERE type IN ('index', 'trigger') "
                    "AND name IN ('uq_approvals_live_binding', 'trg_audit_events_no_update', "
                    "'trg_audit_events_no_delete')"
                ).scalar_one()
                == 0
            )
    finally:
        downgraded_engine.dispose()

    command.upgrade(config, "head")
    upgraded_engine = create_database_engine(config.get_main_option("sqlalchemy.url"))
    try:
        assert set(inspect(upgraded_engine).get_table_names()) == EXPECTED_TABLES
        with upgraded_engine.connect() as connection:
            triggers = {
                row[0]
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='trigger'"
                )
            }
        assert triggers == {
            "trg_audit_events_no_update",
            "trg_audit_events_no_delete",
            "trg_approval_decision_events_no_update",
            "trg_approval_decision_events_no_delete",
        }
    finally:
        upgraded_engine.dispose()


def test_alembic_created_approval_decision_events_are_append_only(
    migrated_database: tuple[Engine, Config],
) -> None:
    engine, _ = migrated_database
    _seed_raw_state(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO approvals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "approval-human",
                "mandate-1",
                "intent-human",
                "0" * 64,
                5,
                "INR",
                "granted",
                "2026-09-01 00:00:00",
                1,
            ),
        )
        connection.exec_driver_sql(
            "INSERT INTO approval_decision_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "approval-audit-1",
                "approval-human",
                "mandate-1",
                "intent-human",
                "0" * 64,
                5,
                "INR",
                "grant",
                "granted",
                "2026-08-30 12:00:00",
                0,
                "trusted_human",
            ),
        )
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.exec_driver_sql(
            "UPDATE approval_decision_events SET replayed = 1 WHERE event_id = 'approval-audit-1'"
        )
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.exec_driver_sql(
            "DELETE FROM approval_decision_events WHERE event_id = 'approval-audit-1'"
        )
