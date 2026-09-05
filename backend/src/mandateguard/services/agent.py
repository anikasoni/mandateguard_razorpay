"""Run a bounded agent proposal through every applicable deterministic guard."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import uuid4

from mandateguard.agent.planner import PurchasePlan, PurchasingPlanner
from mandateguard.core.config import Settings
from mandateguard.db.repositories import ProductRepository
from mandateguard.db.session import SessionFactory
from mandateguard.domain.enums import DecisionOutcome
from mandateguard.services.policy import PolicyService, PolicyServiceResult


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    run_id: str
    checkout_intent_id: str
    plan: PurchasePlan
    status: Literal["blocked", "checkout_reserved", "awaiting_human_approval"]
    steps: tuple[PolicyServiceResult, ...]


class AgentRunService:
    def __init__(self, session_factory: SessionFactory, settings: Settings) -> None:
        self._session_factory = session_factory
        self._policy = PolicyService(session_factory, settings)
        api_key = (
            settings.gemini_api_key.get_secret_value()
            if settings.gemini_api_key is not None
            else None
        )
        self._planner = PurchasingPlanner(api_key=api_key, model=settings.gemini_model)

    def run(
        self,
        *,
        mandate_id: str,
        user_request: str,
        evaluated_at: datetime,
    ) -> AgentRunResult:
        with self._session_factory() as session:
            products = ProductRepository(session).list_all()
        if not products:
            raise RuntimeError("synthetic catalog is empty")
        plan = self._planner.plan(user_request, products)
        product = next(item for item in products if item.product_id == plan.product_id)
        run_id = f"run-{uuid4().hex}"
        intent_id = f"intent-{uuid4().hex}"
        shared = {
            "product_id": product.product_id,
            "checkout_intent_id": intent_id,
            "quantity": plan.quantity,
            "currency": product.currency,
            "quoted_unit_price_paise": product.unit_price_paise,
            "price_version": product.price_version,
            "inventory_version": product.inventory_version,
        }
        requests: list[dict[str, object]] = [
            {
                "request_id": f"{run_id}-get",
                "mandate_id": mandate_id,
                "tool": "get_product",
                "arguments": {"product_id": product.product_id, "currency": product.currency},
            },
            {
                "request_id": f"{run_id}-offer",
                "mandate_id": mandate_id,
                "tool": "present_offer",
                "arguments": {
                    **shared,
                    "claims": {"claimed_inventory_count": plan.claimed_inventory_count},
                },
            },
        ]
        steps: list[PolicyServiceResult] = []
        for request in requests:
            step = self._policy.evaluate(request, evaluated_at=evaluated_at)
            steps.append(step)
            if step.decision.outcome is not DecisionOutcome.ALLOW:
                return AgentRunResult(run_id, intent_id, plan, "blocked", tuple(steps))

        checkout_request: dict[str, object] = {
            "request_id": f"{run_id}-checkout",
            "mandate_id": mandate_id,
            "tool": "create_checkout",
            "arguments": {**shared, "approval_id": None},
        }
        checkout = self._policy.evaluate(checkout_request, evaluated_at=evaluated_at)
        steps.append(checkout)
        if checkout.decision.outcome is DecisionOutcome.ALLOW:
            return AgentRunResult(run_id, intent_id, plan, "checkout_reserved", tuple(steps))
        if checkout.decision.outcome is not DecisionOutcome.REQUEST_APPROVAL:
            return AgentRunResult(run_id, intent_id, plan, "blocked", tuple(steps))

        approval_request: dict[str, object] = {
            "request_id": f"{run_id}-approval",
            "mandate_id": mandate_id,
            "tool": "request_approval",
            "arguments": {**shared, "approval_id": None},
        }
        approval = self._policy.evaluate(approval_request, evaluated_at=evaluated_at)
        steps.append(approval)
        return AgentRunResult(run_id, intent_id, plan, "awaiting_human_approval", tuple(steps))
