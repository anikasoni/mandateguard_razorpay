"""Persistence-only safe projections for malformed untrusted requests.

The Phase 2A canonical helpers intentionally remain unchanged. These bounded,
value-free projections exist solely to make malformed Phase 2B audit records
safe to persist.
"""

import re
from typing import cast

from pydantic import ValidationError

from mandateguard.domain.models import SafeRequestEnvelope, ToolRequest
from mandateguard.policy.canonical import sha256_value

_SAFE_FIELD = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_MAX_SHAPE_FIELDS = 64


def _type_marker(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "mapping"
    if isinstance(value, (list, tuple)):
        return "sequence"
    return "unsupported"


def _bounded_field_shape(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, dict):
        return ()
    safe_items = [
        (key, _type_marker(item))
        for key, item in value.items()
        if isinstance(key, str) and _SAFE_FIELD.fullmatch(key)
    ]
    safe_items.sort()
    unsupported_count = len(value) - len(safe_items)
    bounded = safe_items[:_MAX_SHAPE_FIELDS]
    truncated_count = max(0, len(safe_items) - len(bounded))
    if unsupported_count:
        bounded.append(("unsupported_key", f"count:{unsupported_count}"))
    if truncated_count:
        bounded.append(("truncated", f"count:{truncated_count}"))
    return tuple(bounded)


def safe_persistence_request_envelope(raw: object) -> SafeRequestEnvelope:
    """Project an unparseable request without retaining arbitrary values."""

    mapping = raw if isinstance(raw, dict) else {}
    raw_arguments = mapping.get("arguments")
    arguments = cast(dict[object, object], raw_arguments) if isinstance(raw_arguments, dict) else {}
    shape = {
        "format": "malformed-request-shape-v1",
        "root_type": _type_marker(raw),
        "fields": _bounded_field_shape(mapping),
        "argument_fields": _bounded_field_shape(arguments),
    }
    raw_sha256 = sha256_value(shape)

    return SafeRequestEnvelope(
        request_id=None,
        mandate_id=None,
        tool=None,
        field_names=tuple(item[0] for item in _bounded_field_shape(mapping)),
        argument_field_names=tuple(item[0] for item in _bounded_field_shape(arguments)),
        raw_sha256=raw_sha256,
        semantic_sha256=sha256_value(
            {"format": "unparsed-semantic-v1", "raw_shape_sha256": raw_sha256}
        ),
    )


def safe_validation_error_locations(error: ValidationError) -> tuple[str, ...]:
    """Return bounded, value-free validation paths for malformed audit evidence."""

    locations: set[str] = set()
    for item in error.errors(include_url=False, include_context=False, include_input=False):
        parts = tuple(item["loc"])
        safe_parts = tuple(
            part
            if isinstance(part, str) and _SAFE_FIELD.fullmatch(part)
            else "index"
            if type(part) is int
            else "unsupported"
            for part in parts[:16]
        )
        locations.add(".".join(safe_parts) or "root")
    ordered = sorted(locations)
    if len(ordered) > _MAX_SHAPE_FIELDS:
        return (*ordered[:_MAX_SHAPE_FIELDS], "truncated")
    return tuple(ordered)


def safe_audit_arguments(
    raw: object, request: ToolRequest | None, envelope: SafeRequestEnvelope
) -> dict[str, object]:
    """Return validated arguments or a bounded value-free malformed projection."""

    if request is not None:
        return request.arguments.model_dump(mode="json")
    return {
        "unparsed": True,
        "field_names": envelope.field_names,
        "argument_field_names": envelope.argument_field_names,
        "field_shape": [
            {"name": name, "type": type_name} for name, type_name in _bounded_field_shape(raw)
        ],
        "argument_field_shape": [
            {"name": name, "type": type_name}
            for name, type_name in _bounded_field_shape(
                raw.get("arguments") if isinstance(raw, dict) else None
            )
        ],
        "raw_shape_sha256": envelope.raw_sha256,
        "semantic_fallback_sha256": envelope.semantic_sha256,
        "root_type": _type_marker(raw),
    }
