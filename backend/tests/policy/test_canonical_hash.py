import hashlib

import pytest
from pydantic import TypeAdapter, ValidationError

from mandateguard.domain import ToolRequest
from mandateguard.policy.canonical import canonical_json, intent_hash

EXPECTED_CANONICAL_INTENT_JSON = (
    '{"checkout_intent_id":"intent-1","currency":"INR","mandate_id":"mandate-1",'
    '"observed_inventory_version":4,"observed_price_version":7,"product_id":"product-1",'
    '"quantity":2,"quoted_unit_price_paise":5000}'
)
EXPECTED_INTENT_HASH = "7bac3d1cf8b8c51e68500ecca2999a5c4ba6e8c1cd31e49581dfd036401b0339"


def literal_request() -> dict[str, object]:
    return {
        "request_id": "volatile-request-id",
        "mandate_id": "mandate-1",
        "tool": "create_checkout",
        "arguments": {
            "product_id": "product-1",
            "checkout_intent_id": "intent-1",
            "quantity": 2,
            "currency": "INR",
            "quoted_unit_price_paise": 5_000,
            "price_version": 7,
            "inventory_version": 4,
            "approval_id": None,
        },
    }


def parse(raw: dict[str, object]) -> ToolRequest:
    return TypeAdapter(ToolRequest).validate_python(raw)


def test_independent_canonical_json_and_sha256_vector() -> None:
    projection = {
        "mandate_id": "mandate-1",
        "checkout_intent_id": "intent-1",
        "product_id": "product-1",
        "quantity": 2,
        "currency": "INR",
        "quoted_unit_price_paise": 5_000,
        "observed_price_version": 7,
        "observed_inventory_version": 4,
    }
    assert canonical_json(projection) == EXPECTED_CANONICAL_INTENT_JSON
    assert (
        hashlib.sha256(EXPECTED_CANONICAL_INTENT_JSON.encode()).hexdigest() == EXPECTED_INTENT_HASH
    )
    assert intent_hash(parse(literal_request())) == EXPECTED_INTENT_HASH


@pytest.mark.parametrize(
    ("location", "field", "replacement"),
    [
        ("root", "mandate_id", "mandate-2"),
        ("arguments", "checkout_intent_id", "intent-2"),
        ("arguments", "product_id", "product-2"),
        ("arguments", "quantity", 3),
        ("arguments", "quoted_unit_price_paise", 5_001),
        ("arguments", "currency", "USD"),
        ("arguments", "price_version", 8),
        ("arguments", "inventory_version", 5),
    ],
)
def test_every_semantic_binding_mutation_changes_intent_hash(
    location: str, field: str, replacement: object
) -> None:
    raw = literal_request()
    if location == "root":
        raw[field] = replacement
    else:
        arguments = raw["arguments"]
        assert isinstance(arguments, dict)
        arguments[field] = replacement
    assert intent_hash(parse(raw)) != EXPECTED_INTENT_HASH


def test_mapping_order_does_not_change_intent_hash() -> None:
    raw = literal_request()
    arguments = raw["arguments"]
    assert isinstance(arguments, dict)
    reordered = {
        "arguments": dict(reversed(tuple(arguments.items()))),
        "tool": raw["tool"],
        "mandate_id": raw["mandate_id"],
        "request_id": raw["request_id"],
    }
    assert intent_hash(parse(reordered)) == EXPECTED_INTENT_HASH


def test_volatile_request_and_approval_ids_do_not_enter_intent_hash() -> None:
    first = literal_request()
    second = literal_request()
    second["request_id"] = "different-request-id"
    second_arguments = second["arguments"]
    assert isinstance(second_arguments, dict)
    second_arguments["approval_id"] = "different-approval-id"
    assert intent_hash(parse(first)) == intent_hash(parse(second)) == EXPECTED_INTENT_HASH


@pytest.mark.parametrize(
    ("location", "field"),
    [
        ("root", "mandate_id"),
        ("arguments", "checkout_intent_id"),
        ("arguments", "product_id"),
        ("arguments", "quantity"),
        ("arguments", "quoted_unit_price_paise"),
        ("arguments", "currency"),
        ("arguments", "price_version"),
        ("arguments", "inventory_version"),
    ],
)
def test_required_binding_field_cannot_be_omitted(location: str, field: str) -> None:
    raw = literal_request()
    if location == "root":
        del raw[field]
    else:
        arguments = raw["arguments"]
        assert isinstance(arguments, dict)
        del arguments[field]
    with pytest.raises(ValidationError):
        parse(raw)


def test_unknown_binding_field_cannot_be_silently_added() -> None:
    raw = literal_request()
    arguments = raw["arguments"]
    assert isinstance(arguments, dict)
    arguments["untracked_price_version"] = 99
    with pytest.raises(ValidationError):
        parse(raw)
