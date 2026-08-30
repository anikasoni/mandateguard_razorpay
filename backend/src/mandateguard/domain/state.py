from datetime import datetime

from pydantic import model_validator

from mandateguard.domain.models import Approval, CheckoutAttempt, FrozenModel, Mandate, Product
from mandateguard.domain.validation import checked_sum


class EvaluationState(FrozenModel):
    mandate: Mandate
    products: tuple[Product, ...] = ()
    approvals: tuple[Approval, ...] = ()
    checkout_attempts: tuple[CheckoutAttempt, ...] = ()

    @model_validator(mode="after")
    def canonicalize_and_validate(self) -> "EvaluationState":
        product_ids = [item.product_id for item in self.products]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("product IDs must be unique")
        approval_ids = [item.approval_id for item in self.approvals]
        if len(approval_ids) != len(set(approval_ids)):
            raise ValueError("approval IDs must be unique")
        attempt_ids = [item.attempt_id for item in self.checkout_attempts]
        if len(attempt_ids) != len(set(attempt_ids)):
            raise ValueError("attempt IDs must be unique")
        idempotency_keys = [item.idempotency_key for item in self.checkout_attempts]
        if len(idempotency_keys) != len(set(idempotency_keys)):
            raise ValueError("attempt idempotency keys must be unique")
        intent_identities = [
            (item.mandate_id, item.checkout_intent_id) for item in self.checkout_attempts
        ]
        if len(intent_identities) != len(set(intent_identities)):
            raise ValueError("attempt mandate/checkout-intent identities must be unique")
        object.__setattr__(
            self, "products", tuple(sorted(self.products, key=lambda item: item.product_id))
        )
        object.__setattr__(
            self, "approvals", tuple(sorted(self.approvals, key=lambda item: item.approval_id))
        )
        object.__setattr__(
            self,
            "checkout_attempts",
            tuple(sorted(self.checkout_attempts, key=lambda item: item.attempt_id)),
        )
        return self

    def product(self, product_id: str) -> Product | None:
        return next((item for item in self.products if item.product_id == product_id), None)

    def approvals_for(self, mandate_id: str, intent_id: str) -> tuple[Approval, ...]:
        return tuple(
            item
            for item in self.approvals
            if item.mandate_id == mandate_id and item.checkout_intent_id == intent_id
        )

    def attempts_for(self, mandate_id: str, intent_id: str) -> tuple[CheckoutAttempt, ...]:
        return tuple(
            item
            for item in self.checkout_attempts
            if item.mandate_id == mandate_id and item.checkout_intent_id == intent_id
        )

    def committed_spend_at(self, mandate_id: str, evaluated_at: datetime) -> int:
        return checked_sum(
            item.amount_paise
            for item in self.checkout_attempts
            if item.mandate_id == mandate_id and item.contributes_spend_at(evaluated_at)
        )
