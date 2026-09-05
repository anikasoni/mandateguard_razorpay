"""Bounded purchasing-agent demo transport."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.exc import SQLAlchemyError

from mandateguard.agent.planner import AgentPlanningError
from mandateguard.api.dependencies import get_agent_run_service, get_evaluated_at
from mandateguard.api.errors import ApiError
from mandateguard.api.schemas import (
    AgentPlanResponse,
    AgentRunRequest,
    AgentRunResponse,
    AgentStepResponse,
    ErrorResponse,
)
from mandateguard.services.agent import AgentRunService

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post(
    "/runs",
    response_model=AgentRunResponse,
    responses={code: {"model": ErrorResponse} for code in (409, 422, 502, 503)},
)
def run_agent(
    body: AgentRunRequest,
    evaluated_at: Annotated[datetime, Depends(get_evaluated_at)],
    service: Annotated[AgentRunService, Depends(get_agent_run_service)],
) -> AgentRunResponse:
    try:
        result = service.run(
            mandate_id=body.mandate_id,
            user_request=body.user_request,
            evaluated_at=evaluated_at,
        )
    except AgentPlanningError as exc:
        raise ApiError(
            502, "agent_planning_failed", "The purchasing agent could not plan.", retryable=True
        ) from exc
    except SQLAlchemyError as exc:
        raise ApiError(
            503, "database_unavailable", "Database is unavailable.", retryable=True
        ) from exc
    except RuntimeError as exc:
        raise ApiError(
            409, "demo_not_seeded", "The synthetic demo catalog is unavailable."
        ) from exc
    return AgentRunResponse(
        run_id=result.run_id,
        checkout_intent_id=result.checkout_intent_id,
        plan=AgentPlanResponse(
            product_id=result.plan.product_id,
            quantity=result.plan.quantity,
            claimed_inventory_count=result.plan.claimed_inventory_count,
            rationale=result.plan.rationale,
            provider=result.plan.provider,
        ),
        status=result.status,
        steps=tuple(
            AgentStepResponse(
                audit_event_id=step.audit_event_id,
                decision=step.decision,
                approval=step.approval,
                checkout_attempt=step.checkout_attempt,
            )
            for step in result.steps
        ),
    )
