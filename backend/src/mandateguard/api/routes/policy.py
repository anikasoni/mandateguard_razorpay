"""HTTP transport for deterministic policy evaluation."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import TypeAdapter
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from mandateguard.api.dependencies import (
    get_evaluated_at,
    get_policy_service,
    require_json_content_type,
)
from mandateguard.api.errors import ApiError
from mandateguard.api.schemas import (
    ErrorResponse,
    PolicyEvaluationResponse,
)
from mandateguard.db.repositories import RepositoryConflictError
from mandateguard.domain.models import ToolRequest
from mandateguard.services.policy import PolicyService

router = APIRouter(prefix="/policy", tags=["policy"])
_REQUEST_SCHEMA = TypeAdapter(ToolRequest).json_schema()
_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    415: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}


def _map_persistence_error(error: Exception) -> ApiError:
    if isinstance(error, RepositoryConflictError):
        return ApiError(409, "state_conflict", "Persisted policy state changed.", retryable=True)
    if isinstance(error, IntegrityError):
        return ApiError(409, "persistence_conflict", "Policy result could not be persisted.")
    return ApiError(503, "database_unavailable", "Database is unavailable.", retryable=True)


@router.post(
    "/evaluations",
    response_model=PolicyEvaluationResponse,
    responses=_ERROR_RESPONSES,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": _REQUEST_SCHEMA}},
        }
    },
)
async def evaluate_policy(
    request: Request,
    evaluated_at: Annotated[datetime, Depends(get_evaluated_at)],
    service: Annotated[PolicyService, Depends(get_policy_service)],
    _: Annotated[None, Depends(require_json_content_type)],
) -> PolicyEvaluationResponse:
    try:
        raw_request: Any = await request.json()
    except ValueError as exc:
        raise ApiError(400, "invalid_json", "Request body must be valid JSON.") from exc
    try:
        result = service.evaluate(raw_request, evaluated_at=evaluated_at)
    except (RepositoryConflictError, SQLAlchemyError) as exc:
        raise _map_persistence_error(exc) from exc
    return PolicyEvaluationResponse(
        audit_event_id=result.audit_event_id,
        decision=result.decision,
        approval=result.approval,
        checkout_attempt=result.checkout_attempt,
    )
