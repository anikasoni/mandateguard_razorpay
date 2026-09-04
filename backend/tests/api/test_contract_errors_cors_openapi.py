"""Transport contract, CORS, and OpenAPI smoke tests."""

from fastapi.testclient import TestClient

HUMAN_KEY = "local-human-key-for-tests"


def test_human_transport_validation_and_media_type(api_client: TestClient) -> None:
    url = "/api/v1/human/mandates/mandate-1/approvals/approval-1/decisions"
    headers = {"X-MandateGuard-Human-Key": HUMAN_KEY}
    malformed = api_client.post(url, json={"decision": "approve"}, headers=headers)
    media = api_client.post(
        url,
        content="plain",
        headers={**headers, "Content-Type": "text/plain"},
    )

    assert (malformed.status_code, malformed.json()["error"]["code"]) == (
        422,
        "invalid_request",
    )
    assert malformed.json()["error"]["fields"]
    assert (media.status_code, media.json()["error"]["code"]) == (
        415,
        "unsupported_media_type",
    )


def test_policy_post_cors_preflight_and_disallowed_origin(api_client: TestClient) -> None:
    allowed = api_client.options(
        "/api/v1/policy/evaluations",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-mandateguard-human-key",
        },
    )
    denied = api_client.options(
        "/api/v1/policy/evaluations",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "POST" in allowed.headers["access-control-allow-methods"]
    assert "x-mandateguard-human-key" in allowed.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-origin" not in denied.headers


def test_openapi_documents_union_errors_and_human_security(api_client: TestClient) -> None:
    schema = api_client.get("/openapi.json").json()
    paths = schema["paths"]
    phase_2c_paths = {
        path: set(operations) - {"parameters"}
        for path, operations in paths.items()
        if path.startswith(("/api/v1/policy", "/api/v1/human"))
    }
    assert phase_2c_paths == {
        "/api/v1/policy/evaluations": {"post"},
        "/api/v1/human/mandates/{mandate_id}/approvals/{approval_id}/decisions": {"post"},
    }
    policy_post = paths["/api/v1/policy/evaluations"]["post"]
    human_post = paths["/api/v1/human/mandates/{mandate_id}/approvals/{approval_id}/decisions"][
        "post"
    ]

    request_schema = policy_post["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema["discriminator"]["propertyName"] == "tool"
    assert len(request_schema["oneOf"]) == 4
    assert {"200", "400", "409", "415", "503"} <= set(policy_post["responses"])
    assert {"200", "400", "401", "404", "409", "415", "422", "503"} <= set(human_post["responses"])
    assert human_post["security"]
    security_schemes = schema["components"]["securitySchemes"]
    assert any(item.get("name") == "X-MandateGuard-Human-Key" for item in security_schemes.values())
