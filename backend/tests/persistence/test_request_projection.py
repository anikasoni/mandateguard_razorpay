"""Persistence-only malformed request projection tests."""

import hashlib

import pytest
from pydantic import TypeAdapter, ValidationError

from mandateguard.domain import ToolRequest
from mandateguard.policy.canonical import canonical_json
from mandateguard.services.request_projection import (
    safe_audit_arguments,
    safe_persistence_request_envelope,
    safe_validation_error_locations,
)


def test_malformed_unsupported_objects_have_stable_redacted_hashes() -> None:
    class SensitiveObject:
        def __repr__(self) -> str:
            return "SECRET-value-at-0x123456"

    first = {
        "request_id": "SECRET-request",
        "mandate_id": "SECRET-mandate",
        "tool": "SECRET-tool",
        "secret": SensitiveObject(),
    }
    second = {
        "request_id": "different-request",
        "mandate_id": "different-mandate",
        "tool": "different-tool",
        "secret": SensitiveObject(),
    }
    first_envelope = safe_persistence_request_envelope(first)
    second_envelope = safe_persistence_request_envelope(second)

    assert first_envelope.raw_sha256 == second_envelope.raw_sha256
    assert first_envelope.semantic_sha256 == second_envelope.semantic_sha256
    assert first_envelope.request_id is None
    assert first_envelope.mandate_id is None
    assert first_envelope.tool is None
    audit_arguments = safe_audit_arguments(first, None, first_envelope)
    assert {tuple(item.values()) for item in audit_arguments["field_shape"]} == {
        ("mandate_id", "string"),
        ("request_id", "string"),
        ("secret", "unsupported"),
        ("tool", "string"),
    }
    stored = canonical_json(
        {
            "envelope": first_envelope,
            "arguments": audit_arguments,
        }
    )
    assert "SECRET" not in stored
    assert "0x123456" not in stored
    assert "SensitiveObject" not in stored


def test_malformed_semantic_hash_is_explicit_shape_fallback() -> None:
    envelope = safe_persistence_request_envelope(
        {"request_id": "r", "arguments": {"quantity": 1.5}}
    )
    expected = canonical_json(
        {"format": "unparsed-semantic-v1", "raw_shape_sha256": envelope.raw_sha256}
    )
    assert hashlib.sha256(expected.encode()).hexdigest() == envelope.semantic_sha256


def test_validation_locations_never_stringify_arbitrary_keys() -> None:
    class SensitiveKey:
        def __str__(self) -> str:
            return "SECRET-location-at-0x123456"

    with pytest.raises(ValidationError) as captured:
        TypeAdapter(ToolRequest).validate_python({SensitiveKey(): object()})

    stored = canonical_json(safe_validation_error_locations(captured.value))
    assert "SECRET" not in stored
    assert "0x123456" not in stored
