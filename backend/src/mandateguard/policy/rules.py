from collections.abc import Mapping

from mandateguard.domain.enums import (
    ApprovalStatus,
    DecisionOutcome,
    EvidenceStatus,
    ExecutionMode,
    MandateStatus,
    RuleId,
    ToolName,
)
from mandateguard.domain.models import (
    Approval,
    CheckoutAttempt,
    EvidenceFact,
    FinancialIntentArguments,
    PresentOfferArguments,
    RuleEvidence,
)
from mandateguard.domain.validation import IntegerOverflowError, checked_add
from mandateguard.policy.rule import PolicyRule, RuleContext, RuleResult

Facts = Mapping[str, str | int | bool | tuple[str | int | bool | None, ...] | None]


def evidence(
    rule_id: RuleId, status: EvidenceStatus, reason: str, facts: Facts | None = None
) -> RuleEvidence:
    return RuleEvidence(
        rule_id=rule_id,
        status=status,
        reason=reason,
        facts=tuple(
            EvidenceFact(key=key, value=value) for key, value in sorted((facts or {}).items())
        ),
    )


def passed(rule_id: RuleId, reason: str, facts: Facts | None = None) -> RuleResult:
    return RuleResult(evidence(rule_id, EvidenceStatus.PASS, reason, facts))


def failed(rule_id: RuleId, reason: str, facts: Facts | None = None) -> RuleResult:
    return RuleResult(evidence(rule_id, EvidenceStatus.FAIL, reason, facts), DecisionOutcome.BLOCK)


def not_applicable(rule_id: RuleId, reason: str = "rule_not_applicable") -> RuleResult:
    return RuleResult(evidence(rule_id, EvidenceStatus.NOT_APPLICABLE, reason))


def financial_arguments(
    context: RuleContext,
) -> PresentOfferArguments | FinancialIntentArguments | None:
    arguments = context.request.arguments
    return (
        arguments
        if isinstance(arguments, (PresentOfferArguments, FinancialIntentArguments))
        else None
    )


def attempt_matches(context: RuleContext, attempt: CheckoutAttempt) -> bool:
    arguments = financial_arguments(context)
    if arguments is None or context.request_hash is None:
        return False
    return (
        attempt.request_hash == context.request_hash
        and attempt.product_id == arguments.product_id
        and attempt.quantity == arguments.quantity
        and attempt.amount_paise == context.total_paise
        and attempt.currency == arguments.currency
    )


def exact_attempt(context: RuleContext) -> CheckoutAttempt | None:
    arguments = financial_arguments(context)
    if arguments is None:
        return None
    return next(
        (
            item
            for item in context.state.attempts_for(
                context.request.mandate_id, arguments.checkout_intent_id
            )
            if attempt_matches(context, item)
        ),
        None,
    )


def retry_candidate(context: RuleContext) -> CheckoutAttempt | None:
    attempt = exact_attempt(context)
    return attempt if attempt is not None and attempt.retryable else None


class RequestContractRule:
    rule_id = RuleId.REQUEST_CONTRACT

    def evaluate(self, context: RuleContext) -> RuleResult:
        return passed(self.rule_id, "request_contract_valid")


class IntentIdempotencyRule:
    rule_id = RuleId.INTENT_IDEMPOTENCY

    def evaluate(self, context: RuleContext) -> RuleResult:
        arguments = financial_arguments(context)
        if arguments is None:
            return not_applicable(self.rule_id)
        if context.request.tool is ToolName.REQUEST_APPROVAL:
            live_approvals = tuple(
                item
                for item in context.state.approvals_for(
                    context.request.mandate_id, arguments.checkout_intent_id
                )
                if item.status in {ApprovalStatus.PENDING, ApprovalStatus.GRANTED}
                and item.is_live_at(context.evaluated_at)
            )
            if any(
                item.request_hash != context.request_hash
                or item.amount_paise != context.total_paise
                or item.currency != arguments.currency
                for item in live_approvals
            ):
                return failed(
                    self.rule_id,
                    "approval_intent_conflict",
                    {
                        "approval_count": len(live_approvals),
                        "checkout_intent_id": arguments.checkout_intent_id,
                    },
                )
        attempts = context.state.attempts_for(
            context.request.mandate_id, arguments.checkout_intent_id
        )
        if not attempts:
            return passed(self.rule_id, "checkout_intent_unused")
        if any(not attempt_matches(context, item) for item in attempts):
            return failed(
                self.rule_id,
                "checkout_intent_conflict",
                {
                    "attempt_count": len(attempts),
                    "checkout_intent_id": arguments.checkout_intent_id,
                },
            )
        matching = exact_attempt(context)
        if matching is None:
            return failed(
                self.rule_id,
                "checkout_intent_conflict",
                {
                    "attempt_count": len(attempts),
                    "checkout_intent_id": arguments.checkout_intent_id,
                },
            )
        if matching.is_replayable_at(context.evaluated_at):
            return RuleResult(
                evidence(
                    self.rule_id,
                    EvidenceStatus.PASS,
                    "checkout_result_replayable",
                    {"attempt_id": matching.attempt_id},
                ),
                DecisionOutcome.ALLOW,
                ExecutionMode.REPLAY,
            )
        if matching.retryable:
            return RuleResult(
                evidence(
                    self.rule_id,
                    EvidenceStatus.PASS,
                    "checkout_attempt_retry_candidate",
                    {"attempt_id": matching.attempt_id},
                ),
                execution_mode=ExecutionMode.RETRY_EXISTING,
            )
        return failed(
            self.rule_id,
            "checkout_attempt_not_reusable",
            {"attempt_id": matching.attempt_id, "status": matching.status.value},
        )


class MandateStatusRule:
    rule_id = RuleId.MANDATE_STATUS

    def evaluate(self, context: RuleContext) -> RuleResult:
        mandate = context.state.mandate
        if mandate.status is not MandateStatus.ACTIVE:
            return failed(self.rule_id, "mandate_not_active", {"status": mandate.status.value})
        if context.evaluated_at >= mandate.expires_at:
            return failed(
                self.rule_id,
                "mandate_expired",
                {"expires_at": mandate.expires_at.isoformat()},
            )
        return passed(self.rule_id, "mandate_active_and_unexpired")


class CurrencyRule:
    rule_id = RuleId.CURRENCY

    def evaluate(self, context: RuleContext) -> RuleResult:
        request_currency = context.request.arguments.currency
        currencies = [request_currency, context.state.mandate.currency]
        if context.product is not None:
            currencies.append(context.product.currency)
        if any(item != "INR" for item in currencies) or len(set(currencies)) != 1:
            return failed(
                self.rule_id,
                "currency_mismatch_or_unsupported",
                {"currencies": tuple(currencies), "required_currency": "INR"},
            )
        return passed(self.rule_id, "currency_is_consistent_inr")


class CatalogRule:
    rule_id = RuleId.CATALOG

    def evaluate(self, context: RuleContext) -> RuleResult:
        product = context.product
        if product is None:
            return failed(self.rule_id, "product_not_found")
        if not product.active:
            return failed(self.rule_id, "product_inactive", {"product_id": product.product_id})
        arguments = financial_arguments(context)
        if arguments is None:
            return passed(self.rule_id, "catalog_product_available")
        mismatches: list[str] = []
        if arguments.quoted_unit_price_paise != product.unit_price_paise:
            mismatches.append("unit_price_paise")
        if arguments.price_version != product.price_version:
            mismatches.append("price_version")
        if arguments.inventory_version != product.inventory_version:
            mismatches.append("inventory_version")
        if arguments.quantity > product.inventory_count:
            mismatches.append("inventory_count")
        if mismatches:
            return failed(
                self.rule_id,
                "catalog_state_stale_or_unavailable",
                {"mismatches": tuple(mismatches), "product_id": product.product_id},
            )
        return passed(self.rule_id, "catalog_state_current")


class ScopeRule:
    rule_id = RuleId.SCOPE

    def evaluate(self, context: RuleContext) -> RuleResult:
        if context.product is None:
            return not_applicable(self.rule_id, "catalog_product_unavailable")
        mandate = context.state.mandate
        merchant_allowed = context.product.merchant_id in mandate.approved_merchants
        category_allowed = context.product.category_id in mandate.approved_categories
        if not merchant_allowed or not category_allowed:
            return failed(
                self.rule_id,
                "merchant_or_category_out_of_scope",
                {"category_allowed": category_allowed, "merchant_allowed": merchant_allowed},
            )
        return passed(self.rule_id, "merchant_and_category_allowed")


class OfferClaimsRule:
    rule_id = RuleId.OFFER_CLAIMS

    def evaluate(self, context: RuleContext) -> RuleResult:
        arguments = context.request.arguments
        if not isinstance(arguments, PresentOfferArguments):
            return not_applicable(self.rule_id)
        if context.product is None:
            return not_applicable(self.rule_id, "catalog_product_unavailable")
        claims = arguments.claims
        mismatches: list[str] = []
        if (
            claims.claimed_inventory_count is not None
            and claims.claimed_inventory_count != context.product.inventory_count
        ):
            mismatches.append("claimed_inventory_count")
        if (
            claims.claimed_unit_price_paise is not None
            and claims.claimed_unit_price_paise != context.product.unit_price_paise
        ):
            mismatches.append("claimed_unit_price_paise")
        if (
            claims.claimed_offer_expires_at is not None
            and claims.claimed_offer_expires_at != context.product.offer_expires_at
        ):
            mismatches.append("claimed_offer_expires_at")
        if mismatches:
            return failed(
                self.rule_id,
                "structured_offer_claim_mismatch",
                {"mismatches": tuple(mismatches)},
            )
        return passed(self.rule_id, "structured_offer_claims_truthful")


class PerItemCapRule:
    rule_id = RuleId.PER_ITEM_CAP

    def evaluate(self, context: RuleContext) -> RuleResult:
        arguments = financial_arguments(context)
        if arguments is None:
            return not_applicable(self.rule_id)
        if arguments.quoted_unit_price_paise > context.state.mandate.per_item_cap_paise:
            return failed(
                self.rule_id,
                "per_item_cap_exceeded",
                {
                    "cap_paise": context.state.mandate.per_item_cap_paise,
                    "unit_price_paise": arguments.quoted_unit_price_paise,
                },
            )
        return passed(self.rule_id, "per_item_cap_satisfied")


class CumulativeBudgetRule:
    rule_id = RuleId.CUMULATIVE_BUDGET

    def evaluate(self, context: RuleContext) -> RuleResult:
        arguments = financial_arguments(context)
        if arguments is None or context.total_paise is None:
            return not_applicable(self.rule_id)
        try:
            committed = context.state.committed_spend_at(
                context.request.mandate_id, context.evaluated_at
            )
            existing = exact_attempt(context)
            no_new_spend = existing is not None and (
                existing.is_replayable_at(context.evaluated_at)
                or (existing.retryable and existing.contributes_spend_at(context.evaluated_at))
            )
            increment = 0 if no_new_spend else context.total_paise
            projected = checked_add(committed, increment)
        except IntegerOverflowError:
            return failed(self.rule_id, "cumulative_spend_overflow")
        if projected > context.state.mandate.total_budget_paise:
            return failed(
                self.rule_id,
                "cumulative_budget_exceeded",
                {
                    "budget_paise": context.state.mandate.total_budget_paise,
                    "committed_paise": committed,
                    "projected_paise": projected,
                },
            )
        return passed(
            self.rule_id,
            "cumulative_budget_satisfied",
            {"committed_paise": committed, "projected_paise": projected},
        )


def approval_is_valid(context: RuleContext, approval_id: str) -> tuple[bool, str, Approval | None]:
    arguments = financial_arguments(context)
    if arguments is None:
        return False, "approval_not_applicable", None
    approval = next(
        (
            item
            for item in context.state.approvals_for(
                context.request.mandate_id, arguments.checkout_intent_id
            )
            if item.approval_id == approval_id
        ),
        None,
    )
    if approval is None:
        return False, "approval_missing", None
    allowed_statuses = (
        {ApprovalStatus.PENDING, ApprovalStatus.GRANTED}
        if context.request.tool is ToolName.REQUEST_APPROVAL
        else {ApprovalStatus.GRANTED}
    )
    if approval.status not in allowed_statuses:
        return False, "approval_status_invalid", approval
    if not approval.is_live_at(context.evaluated_at):
        return False, "approval_expired", approval
    if (
        approval.request_hash != context.request_hash
        or approval.amount_paise != context.total_paise
        or approval.currency != arguments.currency
    ):
        return False, "approval_binding_mismatch", approval
    return True, "approval_valid", approval


def reusable_consumed_approval(context: RuleContext) -> Approval | None:
    if context.request.tool is not ToolName.CREATE_CHECKOUT:
        return None
    arguments = financial_arguments(context)
    candidate = retry_candidate(context)
    if (
        arguments is None
        or candidate is None
        or not candidate.contributes_spend_at(context.evaluated_at)
        or candidate.approval_id is None
        or (
            isinstance(arguments, FinancialIntentArguments)
            and arguments.approval_id is not None
            and arguments.approval_id != candidate.approval_id
        )
    ):
        return None
    return next(
        (
            item
            for item in context.state.approvals_for(
                context.request.mandate_id, arguments.checkout_intent_id
            )
            if item.approval_id == candidate.approval_id
            and item.status is ApprovalStatus.CONSUMED
            and item.request_hash == context.request_hash
            and item.amount_paise == context.total_paise
            and item.currency == arguments.currency
        ),
        None,
    )


class ApprovalRule:
    rule_id = RuleId.APPROVAL

    def evaluate(self, context: RuleContext) -> RuleResult:
        arguments = financial_arguments(context)
        if not isinstance(arguments, FinancialIntentArguments):
            return not_applicable(self.rule_id)
        reused = reusable_consumed_approval(context)
        if reused is not None:
            return passed(
                self.rule_id,
                "consumed_approval_bound_to_active_retry_reservation",
                {"approval_id": reused.approval_id},
            )
        if arguments.approval_id is None:
            return passed(self.rule_id, "approval_not_supplied")
        valid, reason, approval = approval_is_valid(context, arguments.approval_id)
        if not valid:
            facts: dict[str, str] = {"approval_id": arguments.approval_id}
            if approval is not None:
                facts["approval_status"] = approval.status.value
            return failed(self.rule_id, reason, facts)
        return passed(self.rule_id, reason, {"approval_id": arguments.approval_id})


def matching_live_approval(context: RuleContext) -> Approval | None:
    arguments = financial_arguments(context)
    if arguments is None:
        return None
    return next(
        (
            item
            for item in context.state.approvals_for(
                context.request.mandate_id, arguments.checkout_intent_id
            )
            if item.status in {ApprovalStatus.PENDING, ApprovalStatus.GRANTED}
            and item.is_live_at(context.evaluated_at)
            and item.request_hash == context.request_hash
            and item.amount_paise == context.total_paise
            and item.currency == arguments.currency
        ),
        None,
    )


class AuthorizationRule:
    rule_id = RuleId.AUTHORIZATION

    def evaluate(self, context: RuleContext) -> RuleResult:
        arguments = context.request.arguments
        if not isinstance(arguments, FinancialIntentArguments) or context.total_paise is None:
            return not_applicable(self.rule_id)
        threshold = context.state.mandate.approval_threshold_paise
        needs_approval = context.total_paise >= threshold
        if context.request.tool is ToolName.REQUEST_APPROVAL:
            if not needs_approval:
                return RuleResult(
                    evidence(
                        self.rule_id,
                        EvidenceStatus.FAIL,
                        "approval_not_required",
                        {"amount_paise": context.total_paise, "threshold_paise": threshold},
                    ),
                    DecisionOutcome.BLOCK,
                )
            existing = matching_live_approval(context)
            return RuleResult(
                evidence(
                    self.rule_id,
                    EvidenceStatus.PASS,
                    "approval_request_replayed" if existing else "approval_creation_allowed",
                    {"approval_id": existing.approval_id if existing else None},
                ),
                DecisionOutcome.ALLOW,
                ExecutionMode.REPLAY if existing else ExecutionMode.EXECUTE,
            )
        if not needs_approval:
            return RuleResult(
                evidence(self.rule_id, EvidenceStatus.PASS, "checkout_below_approval_threshold"),
                DecisionOutcome.ALLOW,
                ExecutionMode.EXECUTE,
            )
        if reusable_consumed_approval(context) is not None:
            return RuleResult(
                evidence(
                    self.rule_id,
                    EvidenceStatus.PASS,
                    "active_retry_reservation_already_authorized",
                ),
                DecisionOutcome.ALLOW,
                ExecutionMode.EXECUTE,
            )
        if arguments.approval_id is None:
            return RuleResult(
                evidence(
                    self.rule_id,
                    EvidenceStatus.FAIL,
                    "checkout_requires_approval",
                    {"amount_paise": context.total_paise, "threshold_paise": threshold},
                ),
                DecisionOutcome.REQUEST_APPROVAL,
            )
        return RuleResult(
            evidence(self.rule_id, EvidenceStatus.PASS, "checkout_has_bound_approval"),
            DecisionOutcome.ALLOW,
            ExecutionMode.EXECUTE,
        )


ORDERED_RULES: tuple[PolicyRule, ...] = (
    RequestContractRule(),
    IntentIdempotencyRule(),
    MandateStatusRule(),
    CurrencyRule(),
    CatalogRule(),
    ScopeRule(),
    OfferClaimsRule(),
    PerItemCapRule(),
    CumulativeBudgetRule(),
    ApprovalRule(),
    AuthorizationRule(),
)
