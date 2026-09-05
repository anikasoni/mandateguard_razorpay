"""Final demo vertical-slice integration tests."""

import hashlib
import hmac
from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from mandateguard.core.config import Settings
from mandateguard.demo.seed import seed_demo_data
from mandateguard.integrations.razorpay import RazorpayOrder, RazorpayOrdersClient


def test_offline_agent_is_bounded_by_policy(api_client: TestClient) -> None:
    seed_demo_data(api_client.app.state.database_session_factory)
    response = api_client.post(
        "/api/v1/agent/runs",
        json={"mandate_id": "mandate-demo", "user_request": "Buy one ergonomic chair"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["plan"]["provider"] == "offline_demo"
    assert body["status"] == "blocked"
    assert body["steps"][-1]["decision"]["rule_id"] == "MG-008"
    assert body["external_execution_authorized"] is False


def test_mandatebench_matches_all_frozen_gold_cases(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/benchmark/report")

    assert response.status_code == 200
    body = response.json()
    assert (body["gold_passed"], body["scenario_count"]) == (20, 20)
    assert body["metrics"]["mandateguard"] == {
        "violation_catch_rate": 100,
        "false_block_rate": 0,
        "decision_accuracy": 100,
    }
    assert "not live LLM measurements" in body["baseline_note"]


def test_guarded_checkout_creates_one_simulated_order(
    api_client: TestClient,
    request_factory: Callable[..., dict[str, Any]],
) -> None:
    guarded = api_client.post(
        "/api/v1/policy/evaluations",
        json=request_factory("create_checkout", quantity=1),
    )
    attempt_id = guarded.json()["checkout_attempt"]["attempt_id"]

    first = api_client.post("/api/v1/payments/orders", json={"attempt_id": attempt_id})
    replay = api_client.post("/api/v1/payments/orders", json={"attempt_id": attempt_id})

    assert first.status_code == 200
    assert first.json()["provider_mode"] == "simulated"
    assert first.json()["replayed"] is False
    assert replay.json()["provider_order_id"] == first.json()["provider_order_id"]
    assert replay.json()["replayed"] is True


def test_payment_order_rejects_unknown_attempt(api_client: TestClient) -> None:
    response = api_client.post("/api/v1/payments/orders", json={"attempt_id": "attempt-missing"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "checkout_attempt_not_found"


def test_test_mode_order_and_backend_signature_verification(
    api_client: TestClient,
    request_factory: Callable[..., dict[str, Any]],
    monkeypatch: Any,
) -> None:
    secret = "test-secret-value"
    current = api_client.app.state.settings
    api_client.app.state.settings = Settings(
        _env_file=None,
        database_url=current.database_url,
        razorpay_key_id="rzp_test_example",
        razorpay_key_secret=secret,
    )

    def fake_create_order(
        self: RazorpayOrdersClient,
        *,
        amount_paise: int,
        currency: str,
        receipt: str,
        attempt_id: str,
    ) -> RazorpayOrder:
        del self, receipt, attempt_id
        return RazorpayOrder("order_test_example", amount_paise, currency, "created")

    monkeypatch.setattr(RazorpayOrdersClient, "create_order", fake_create_order)
    guarded = api_client.post(
        "/api/v1/policy/evaluations",
        json=request_factory("create_checkout", quantity=1),
    ).json()
    attempt_id = guarded["checkout_attempt"]["attempt_id"]
    order = api_client.post("/api/v1/payments/orders", json={"attempt_id": attempt_id})
    assert order.json()["provider_mode"] == "razorpay_test"

    payment_id = "pay_test_example"
    signature = hmac.new(
        secret.encode(),
        f"order_test_example|{payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    invalid = api_client.post(
        "/api/v1/payments/verify",
        json={
            "provider_order_id": "order_test_example",
            "provider_payment_id": payment_id,
            "signature": "0" * 64,
        },
    )
    verified = api_client.post(
        "/api/v1/payments/verify",
        json={
            "provider_order_id": "order_test_example",
            "provider_payment_id": payment_id,
            "signature": signature,
        },
    )
    replay = api_client.post(
        "/api/v1/payments/verify",
        json={
            "provider_order_id": "order_test_example",
            "provider_payment_id": payment_id,
            "signature": signature,
        },
    )

    assert invalid.status_code == 409
    assert verified.status_code == 200
    assert verified.json()["status"] == "paid"
    assert replay.json()["replayed"] is True
