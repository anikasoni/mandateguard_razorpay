from enum import StrEnum


class ToolName(StrEnum):
    GET_PRODUCT = "get_product"
    PRESENT_OFFER = "present_offer"
    REQUEST_APPROVAL = "request_approval"
    CREATE_CHECKOUT = "create_checkout"


class DecisionOutcome(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    REQUEST_APPROVAL = "request_approval"


class EvidenceStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"


class ExecutionMode(StrEnum):
    EXECUTE = "execute"
    REPLAY = "replay"
    RETRY_EXISTING = "retry_existing"
    NONE = "none"


class MandateStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"
    FULFILLED = "fulfilled"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    GRANTED = "granted"
    REJECTED = "rejected"
    REVOKED = "revoked"
    CONSUMED = "consumed"


class CheckoutStatus(StrEnum):
    RESERVED = "reserved"
    CREATED = "created"
    COMPLETED = "completed"
    RETRYABLE_FAILED = "retryable_failed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RuleId(StrEnum):
    REQUEST_CONTRACT = "MG-001"
    INTENT_IDEMPOTENCY = "MG-002"
    MANDATE_STATUS = "MG-003"
    CURRENCY = "MG-004"
    CATALOG = "MG-005"
    SCOPE = "MG-006"
    OFFER_CLAIMS = "MG-007"
    PER_ITEM_CAP = "MG-008"
    CUMULATIVE_BUDGET = "MG-009"
    APPROVAL = "MG-010"
    AUTHORIZATION = "MG-011"
