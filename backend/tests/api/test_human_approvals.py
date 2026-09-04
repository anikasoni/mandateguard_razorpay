"""Trusted human approval API integration behavior."""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from mandateguard.api.dependencies import get_evaluated_at
from mandateguard.db.models import ApprovalDecisionEventRecord, ApprovalRecord

HUMAN_KEY = "local-human-key-for-tests"


def _approval_request(
    request_factory: Callable[..., dict[str, Any]], intent: str
) -> dict[str, Any]:
    return request_factory("request_approval", checkout_intent_id=intent)


def _create_approval(
    client: TestClient,
    request_factory: Callable[..., dict[str, Any]],
    intent: str,
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/policy/evaluations", json=_approval_request(request_factory, intent)
    )
    assert response.status_code == 200
    approval = response.json()["approval"]
    assert approval is not None
    return approval


def _decide(client: TestClient, approval: dict[str, Any], decision: str) -> Any:
    return client.post(
        f"/api/v1/human/mandates/{approval['mandate_id']}/approvals/"
        f"{approval['approval_id']}/decisions",
        json={"checkout_intent_id": approval["checkout_intent_id"], "decision": decision},
        headers={"X-MandateGuard-Human-Key": HUMAN_KEY},
    )


def _event_count(client: TestClient) -> int:
    with client.app.state.database_session_factory() as session:
        return session.scalar(select(func.count()).select_from(ApprovalDecisionEventRecord)) or 0


def test_grant_reject_and_identical_replays(
    api_client: TestClient,
    request_factory: Callable[..., dict[str, Any]],
    now: datetime,
) -> None:
    api_client.app.dependency_overrides[get_evaluated_at] = lambda: now
    granted = _create_approval(api_client, request_factory, "intent-grant")
    rejected = _create_approval(api_client, request_factory, "intent-reject")

    grant = _decide(api_client, granted, "grant")
    grant_replay = _decide(api_client, granted, "grant")
    reject = _decide(api_client, rejected, "reject")
    reject_replay = _decide(api_client, rejected, "reject")

    assert (grant.status_code, grant.json()["approval"]["status"], grant.json()["replayed"]) == (
        200,
        "granted",
        False,
    )
    assert grant_replay.json()["replayed"] is True
    assert (reject.status_code, reject.json()["approval"]["status"]) == (200, "rejected")
    assert reject_replay.json()["replayed"] is True
    assert _event_count(api_client) == 4


def test_auth_binding_expiry_and_conflict_errors_do_not_audit(
    api_client: TestClient,
    request_factory: Callable[..., dict[str, Any]],
    now: datetime,
) -> None:
    api_client.app.dependency_overrides[get_evaluated_at] = lambda: now
    approval = _create_approval(api_client, request_factory, "intent-errors")
    url = (
        f"/api/v1/human/mandates/{approval['mandate_id']}/approvals/"
        f"{approval['approval_id']}/decisions"
    )
    body = {"checkout_intent_id": approval["checkout_intent_id"], "decision": "grant"}

    missing = api_client.post(url, json=body)
    wrong = api_client.post(
        url, json=body, headers={"X-MandateGuard-Human-Key": "incorrect-human-key"}
    )
    mismatch = api_client.post(
        url,
        json={**body, "checkout_intent_id": "other-intent"},
        headers={"X-MandateGuard-Human-Key": HUMAN_KEY},
    )
    assert missing.json() == wrong.json()
    assert (missing.status_code, missing.json()["error"]["code"]) == (
        401,
        "human_authentication_required",
    )
    assert mismatch.json()["error"]["code"] == "approval_binding_mismatch"
    assert _event_count(api_client) == 0

    granted = _decide(api_client, approval, "grant")
    conflict = _decide(api_client, approval, "reject")
    assert granted.status_code == 200
    assert (conflict.status_code, conflict.json()["error"]["code"]) == (
        409,
        "approval_state_conflict",
    )
    assert _event_count(api_client) == 1

    expired = _create_approval(api_client, request_factory, "intent-expired")
    api_client.app.dependency_overrides[get_evaluated_at] = lambda: now + timedelta(minutes=16)
    expired_response = _decide(api_client, expired, "grant")
    assert (expired_response.status_code, expired_response.json()["error"]["code"]) == (
        409,
        "approval_expired",
    )
    with api_client.app.state.database_session_factory() as session:
        stored = session.get(ApprovalRecord, expired["approval_id"])
        assert stored is not None
        assert stored.status == "pending"
    assert _event_count(api_client) == 1


def test_granted_approval_is_consumed_by_exact_checkout(
    api_client: TestClient,
    request_factory: Callable[..., dict[str, Any]],
    now: datetime,
) -> None:
    api_client.app.dependency_overrides[get_evaluated_at] = lambda: now
    approval = _create_approval(api_client, request_factory, "intent-approved-checkout")
    assert _decide(api_client, approval, "grant").status_code == 200

    checkout = request_factory(
        "create_checkout",
        checkout_intent_id="intent-approved-checkout",
        approval_id=approval["approval_id"],
    )
    response = api_client.post("/api/v1/policy/evaluations", json=checkout)
    assert response.status_code == 200
    assert response.json()["decision"]["outcome"] == "allow"
    assert response.json()["checkout_attempt"]["approval_id"] == approval["approval_id"]
    with api_client.app.state.database_session_factory() as session:
        stored = session.get(ApprovalRecord, approval["approval_id"])
        assert stored is not None
        assert (stored.status, stored.live_binding) == ("consumed", 0)
