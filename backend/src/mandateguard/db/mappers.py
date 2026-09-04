"""Field-complete mappings between Phase 2A domain models and database records."""

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TypeGuard

from mandateguard.db.models import (
    ApprovalRecord,
    AuditEventRecord,
    CheckoutAttemptRecord,
    MandateCategoryScopeRecord,
    MandateMerchantScopeRecord,
    MandateRecord,
    ProductRecord,
)
from mandateguard.domain.enums import ApprovalStatus, CheckoutStatus, MandateStatus
from mandateguard.domain.models import (
    Approval,
    CheckoutAttempt,
    GuardDecision,
    Mandate,
    Product,
)
from mandateguard.domain.validation import normalize_utc

type JsonScalar = str | int | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


def _is_string_keyed(value: Mapping[object, object]) -> TypeGuard[Mapping[str, object]]:
    return all(isinstance(key, str) for key in value)


def strict_json_value(value: object) -> JsonValue:
    """Return a JSON-safe value while rejecting floats and arbitrary Python objects."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Mapping):
        if not _is_string_keyed(value):
            raise TypeError("canonical JSON mappings require string keys")
        return {key: strict_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [strict_json_value(item) for item in value]
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json_text(value: object) -> str:
    """Serialize a strictly JSON-safe value in the canonical storage format."""

    return json.dumps(
        strict_json_value(value), ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )


def mandate_to_records(
    mandate: Mandate,
) -> tuple[
    MandateRecord,
    tuple[MandateMerchantScopeRecord, ...],
    tuple[MandateCategoryScopeRecord, ...],
]:
    record = MandateRecord(
        mandate_id=mandate.mandate_id,
        status=mandate.status.value,
        currency=mandate.currency,
        total_budget_paise=mandate.total_budget_paise,
        per_item_cap_paise=mandate.per_item_cap_paise,
        approval_threshold_paise=mandate.approval_threshold_paise,
        expires_at=mandate.expires_at,
    )
    merchants = tuple(
        MandateMerchantScopeRecord(mandate_id=mandate.mandate_id, merchant_id=item)
        for item in sorted(mandate.approved_merchants)
    )
    categories = tuple(
        MandateCategoryScopeRecord(mandate_id=mandate.mandate_id, category_id=item)
        for item in sorted(mandate.approved_categories)
    )
    return record, merchants, categories


def mandate_from_record(
    record: MandateRecord,
    merchants: Sequence[MandateMerchantScopeRecord],
    categories: Sequence[MandateCategoryScopeRecord],
) -> Mandate:
    return Mandate(
        mandate_id=record.mandate_id,
        status=MandateStatus(record.status),
        currency=record.currency,
        total_budget_paise=record.total_budget_paise,
        per_item_cap_paise=record.per_item_cap_paise,
        approval_threshold_paise=record.approval_threshold_paise,
        approved_merchants=frozenset(item.merchant_id for item in merchants),
        approved_categories=frozenset(item.category_id for item in categories),
        expires_at=record.expires_at,
    )


def product_to_record(product: Product) -> ProductRecord:
    return ProductRecord(
        product_id=product.product_id,
        merchant_id=product.merchant_id,
        category_id=product.category_id,
        currency=product.currency,
        unit_price_paise=product.unit_price_paise,
        inventory_count=product.inventory_count,
        price_version=product.price_version,
        inventory_version=product.inventory_version,
        active=product.active,
        offer_expires_at=product.offer_expires_at,
    )


def product_from_record(record: ProductRecord) -> Product:
    return Product(
        product_id=record.product_id,
        merchant_id=record.merchant_id,
        category_id=record.category_id,
        currency=record.currency,
        unit_price_paise=record.unit_price_paise,
        inventory_count=record.inventory_count,
        price_version=record.price_version,
        inventory_version=record.inventory_version,
        active=record.active,
        offer_expires_at=record.offer_expires_at,
    )


def approval_to_record(approval: Approval, *, evaluated_at: datetime) -> ApprovalRecord:
    timestamp = normalize_utc(evaluated_at)
    live_binding = int(
        approval.status in {ApprovalStatus.PENDING, ApprovalStatus.GRANTED}
        and approval.is_live_at(timestamp)
    )
    return ApprovalRecord(
        approval_id=approval.approval_id,
        mandate_id=approval.mandate_id,
        checkout_intent_id=approval.checkout_intent_id,
        request_hash=approval.request_hash,
        amount_paise=approval.amount_paise,
        currency=approval.currency,
        status=approval.status.value,
        expires_at=approval.expires_at,
        live_binding=live_binding,
    )


def approval_from_record(record: ApprovalRecord) -> Approval:
    return Approval(
        approval_id=record.approval_id,
        mandate_id=record.mandate_id,
        checkout_intent_id=record.checkout_intent_id,
        request_hash=record.request_hash,
        amount_paise=record.amount_paise,
        currency=record.currency,
        status=ApprovalStatus(record.status),
        expires_at=record.expires_at,
    )


def checkout_attempt_to_record(attempt: CheckoutAttempt) -> CheckoutAttemptRecord:
    return CheckoutAttemptRecord(
        attempt_id=attempt.attempt_id,
        idempotency_key=attempt.idempotency_key,
        mandate_id=attempt.mandate_id,
        checkout_intent_id=attempt.checkout_intent_id,
        request_hash=attempt.request_hash,
        product_id=attempt.product_id,
        quantity=attempt.quantity,
        amount_paise=attempt.amount_paise,
        currency=attempt.currency,
        status=attempt.status.value,
        reservation_expires_at=attempt.reservation_expires_at,
        approval_id=attempt.approval_id,
    )


def checkout_attempt_from_record(record: CheckoutAttemptRecord) -> CheckoutAttempt:
    return CheckoutAttempt(
        attempt_id=record.attempt_id,
        idempotency_key=record.idempotency_key,
        mandate_id=record.mandate_id,
        checkout_intent_id=record.checkout_intent_id,
        request_hash=record.request_hash,
        product_id=record.product_id,
        quantity=record.quantity,
        amount_paise=record.amount_paise,
        currency=record.currency,
        status=CheckoutStatus(record.status),
        reservation_expires_at=record.reservation_expires_at,
        approval_id=record.approval_id,
    )


def audit_record_from_decision(
    *,
    event_id: str,
    decision: GuardDecision,
    arguments: Mapping[str, object],
    effect_approval_id: str | None = None,
    effect_attempt_id: str | None = None,
) -> AuditEventRecord:
    envelope = decision.request.model_dump(mode="json")
    evidence = [item.model_dump(mode="json") for item in decision.evidence]
    return AuditEventRecord(
        event_id=event_id,
        mandate_id=decision.request.mandate_id,
        request_id=decision.request.request_id,
        tool_called=decision.request.tool,
        arguments_json=canonical_json_text(arguments),
        request_envelope_json=canonical_json_text(envelope),
        rule_invoked=decision.rule_id.value,
        evidence_json=canonical_json_text(evidence),
        decision=decision.outcome.value,
        execution_mode=decision.execution_mode.value,
        policy_version=decision.policy_version,
        reason=decision.reason,
        evaluated_at=decision.evaluated_at,
        fingerprint=decision.fingerprint,
        effect_approval_id=effect_approval_id,
        effect_attempt_id=effect_attempt_id,
    )


def decision_from_audit_record(record: AuditEventRecord) -> GuardDecision:
    return GuardDecision.model_validate(
        {
            "outcome": record.decision,
            "rule_id": record.rule_invoked,
            "reason": record.reason,
            "evidence": json.loads(record.evidence_json),
            "execution_mode": record.execution_mode,
            "policy_version": record.policy_version,
            "evaluated_at": record.evaluated_at,
            "request": json.loads(record.request_envelope_json),
            "fingerprint": record.fingerprint,
        }
    )
