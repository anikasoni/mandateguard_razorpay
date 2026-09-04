"""Policy API integration behavior."""

from collections.abc import Callable
from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from mandateguard.api.dependencies import get_evaluated_at, get_policy_service
from mandateguard.db.models import AuditEventRecord, CheckoutAttemptRecord


def _count(client: TestClient, model: type[Any]) -> int:
    factory = client.app.state.database_session_factory
    with factory() as session:
        return session.scalar(select(func.count()).select_from(model)) or 0


@pytest.mark.parametrize(
    ("tool", "expected"),
    [
        ("get_product", "allow"),
        ("present_offer", "allow"),
        ("request_approval", "allow"),
        ("create_checkout", "request_approval"),
    ],
)
def test_every_policy_tool_success_path(
    tool: str,
    expected: str,
    api_client: TestClient,
    request_factory: Callable[..., dict[str, Any]],
    now: datetime,
) -> None:
    api_client.app.dependency_overrides[get_evaluated_at] = lambda: now
    response = api_client.post("/api/v1/policy/evaluations", json=request_factory(tool))

    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["outcome"] == expected
    assert len(body["decision"]["evidence"]) == 11
    assert body["decision"]["evaluated_at"].endswith("Z")
    assert body["external_execution_authorized"] is False
    assert len(body["decision"]["fingerprint"]) == 64


def test_malformed_unknown_and_invalid_json_behavior(
    api_client: TestClient,
    request_factory: Callable[..., dict[str, Any]],
) -> None:
    malformed = api_client.post(
        "/api/v1/policy/evaluations",
        json={"tool": "create_checkout", "arguments": {"quantity": "two"}},
    )
    unknown = request_factory("get_product")
    unknown["mandate_id"] = "missing-mandate"
    missing = api_client.post("/api/v1/policy/evaluations", json=unknown)
    invalid = api_client.post(
        "/api/v1/policy/evaluations",
        content="{broken",
        headers={"Content-Type": "application/json"},
    )
    media = api_client.post(
        "/api/v1/policy/evaluations",
        content="plain",
        headers={"Content-Type": "text/plain"},
    )

    assert (malformed.status_code, malformed.json()["decision"]["rule_id"]) == (200, "MG-001")
    assert (missing.status_code, missing.json()["decision"]["reason"]) == (200, "mandate_not_found")
    assert invalid.json() == {
        "error": {
            "code": "invalid_json",
            "message": "Request body must be valid JSON.",
            "retryable": False,
        }
    }
    assert (media.status_code, media.json()["error"]["code"]) == (415, "unsupported_media_type")
    assert _count(api_client, AuditEventRecord) == 2


def test_checkout_replay_is_non_executing(
    api_client: TestClient,
    request_factory: Callable[..., dict[str, Any]],
) -> None:
    request = request_factory("create_checkout", quantity=1)
    first = api_client.post("/api/v1/policy/evaluations", json=request)
    replay = api_client.post("/api/v1/policy/evaluations", json=request)
    assert first.json()["decision"]["execution_mode"] == "execute"
    assert replay.json()["decision"]["execution_mode"] == "replay"
    assert first.json()["checkout_attempt"] == replay.json()["checkout_attempt"]
    assert replay.json()["external_execution_authorized"] is False
    assert _count(api_client, CheckoutAttemptRecord) == 1
    assert _count(api_client, AuditEventRecord) == 2


def test_checkout_intent_conflict_is_audited_policy_result(
    api_client: TestClient,
    request_factory: Callable[..., dict[str, Any]],
) -> None:
    first = request_factory("create_checkout", quantity=1, checkout_intent_id="shared-intent")
    conflict = request_factory("create_checkout", quantity=2, checkout_intent_id="shared-intent")

    assert api_client.post("/api/v1/policy/evaluations", json=first).status_code == 200
    response = api_client.post("/api/v1/policy/evaluations", json=conflict)

    assert response.status_code == 200
    assert response.json()["decision"]["reason"] == "checkout_intent_conflict"
    assert _count(api_client, CheckoutAttemptRecord) == 1
    assert _count(api_client, AuditEventRecord) == 2


def test_database_operational_failure_has_stable_503(api_client: TestClient) -> None:
    class LockedPolicyService:
        def evaluate(self, raw_request: object, *, evaluated_at: datetime) -> None:
            del raw_request, evaluated_at
            raise OperationalError("BEGIN IMMEDIATE", {}, RuntimeError("database is locked"))

    api_client.app.dependency_overrides[get_policy_service] = LockedPolicyService
    response = api_client.post("/api/v1/policy/evaluations", json={})

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "database_unavailable",
            "message": "Database is unavailable.",
            "retryable": True,
        }
    }
    assert "locked" not in response.text
    assert _count(api_client, AuditEventRecord) == 0
