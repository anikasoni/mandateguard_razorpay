import hashlib
import json
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel

from mandateguard.domain.models import (
    Approval,
    CheckoutAttempt,
    FinancialIntentArguments,
    Mandate,
    PresentOfferArguments,
    Product,
    RuleEvidence,
    SafeRequestEnvelope,
    ToolRequest,
)

VOLATILE_IDENTIFIER_KEYS = frozenset(
    {
        "request_id",
        "approval_id",
        "attempt_id",
        "idempotency_key",
        "audit_id",
        "audit_event_id",
        "event_id",
    }
)


def canonical_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return canonical_value(value.model_dump(mode="python"))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {str(key): canonical_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (set, frozenset)):
        normalized = [canonical_value(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, (list, tuple)):
        return [canonical_value(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return {"python_type": type(value).__name__}


def canonical_json(value: Any) -> str:
    return json.dumps(
        canonical_value(value), ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def semantic_raw_projection(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): semantic_raw_projection(item)
            for key, item in value.items()
            if str(key) not in VOLATILE_IDENTIFIER_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [semantic_raw_projection(item) for item in value]
    return value


def safe_request_envelope(raw: object) -> SafeRequestEnvelope:
    mapping = raw if isinstance(raw, dict) else {}
    arguments = mapping.get("arguments") if isinstance(mapping.get("arguments"), dict) else {}

    def safe_string(key: str) -> str | None:
        value = mapping.get(key)
        return value if isinstance(value, str) and len(value) <= 128 else None

    return SafeRequestEnvelope(
        request_id=safe_string("request_id"),
        mandate_id=safe_string("mandate_id"),
        tool=safe_string("tool"),
        field_names=tuple(sorted(str(key) for key in mapping)) if isinstance(mapping, dict) else (),
        argument_field_names=(
            tuple(sorted(str(key) for key in arguments)) if isinstance(arguments, dict) else ()
        ),
        raw_sha256=sha256_value(raw),
        semantic_sha256=sha256_value(semantic_raw_projection(raw)),
    )


def intent_arguments(
    request: ToolRequest,
) -> PresentOfferArguments | FinancialIntentArguments | None:
    arguments = request.arguments
    if isinstance(arguments, (PresentOfferArguments, FinancialIntentArguments)):
        return arguments
    return None


def intent_hash(request: ToolRequest) -> str | None:
    arguments = intent_arguments(request)
    if arguments is None:
        return None
    return sha256_value(
        {
            "mandate_id": request.mandate_id,
            "checkout_intent_id": arguments.checkout_intent_id,
            "product_id": arguments.product_id,
            "quantity": arguments.quantity,
            "currency": arguments.currency,
            "quoted_unit_price_paise": arguments.quoted_unit_price_paise,
            "observed_price_version": arguments.price_version,
            "observed_inventory_version": arguments.inventory_version,
        }
    )


def semantic_request_projection(request: ToolRequest) -> dict[str, Any]:
    arguments = request.arguments.model_dump(mode="python")
    arguments.pop("approval_id", None)
    return {
        "mandate_id": request.mandate_id,
        "tool": request.tool,
        "arguments": arguments,
    }


def semantic_mandate_projection(mandate: Mandate) -> dict[str, Any]:
    return mandate.model_dump(mode="python")


def semantic_product_projection(product: Product | None) -> dict[str, Any] | None:
    return product.model_dump(mode="python") if product is not None else None


def semantic_approval_projection(approval: Approval) -> dict[str, Any]:
    return approval.model_dump(mode="python", exclude={"approval_id"})


def semantic_attempt_projection(attempt: CheckoutAttempt) -> dict[str, Any]:
    projection = attempt.model_dump(
        mode="python", exclude={"attempt_id", "idempotency_key", "approval_id"}
    )
    projection["has_bound_approval"] = attempt.approval_id is not None
    return projection


def semantic_evidence_projection(item: RuleEvidence) -> dict[str, Any]:
    return {
        "rule_id": item.rule_id,
        "status": item.status,
        "reason": item.reason,
        "facts": tuple(fact for fact in item.facts if fact.key not in VOLATILE_IDENTIFIER_KEYS),
    }


def semantic_sorted(values: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    return tuple(sorted(values, key=canonical_json))
