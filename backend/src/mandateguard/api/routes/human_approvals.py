"""Trusted human-only approval decision transport."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from mandateguard.api.dependencies import (
    get_evaluated_at,
    get_human_approval_service,
    require_human_key,
    require_json_content_type,
)
from mandateguard.api.errors import ApiError
from mandateguard.api.schemas import (
    ErrorResponse,
    HumanApprovalDecisionRequest,
    HumanApprovalDecisionResponse,
)
from mandateguard.db.repositories import RepositoryConflictError
from mandateguard.domain.validation import Identifier
from mandateguard.services.approvals import (
    ApprovalBindingMismatchError,
    ApprovalExpiredError,
    ApprovalNotFoundError,
    ApprovalStateConflictError,
    HumanApprovalService,
)

router = APIRouter(
    prefix="/human",
    tags=["human approvals"],
    dependencies=[Depends(require_human_key), Depends(require_json_content_type)],
)


@router.post(
    "/mandates/{mandate_id}/approvals/{approval_id}/decisions",
    response_model=HumanApprovalDecisionResponse,
    responses={code: {"model": ErrorResponse} for code in (400, 401, 404, 409, 415, 422, 503)},
)
def decide_approval(
    mandate_id: Identifier,
    approval_id: Identifier,
    body: HumanApprovalDecisionRequest,
    evaluated_at: Annotated[datetime, Depends(get_evaluated_at)],
    service: Annotated[HumanApprovalService, Depends(get_human_approval_service)],
) -> HumanApprovalDecisionResponse:
    try:
        result = service.decide(
            mandate_id=mandate_id,
            approval_id=approval_id,
            checkout_intent_id=body.checkout_intent_id,
            decision=body.decision,
            evaluated_at=evaluated_at,
        )
    except ApprovalNotFoundError as exc:
        raise ApiError(404, "approval_not_found", "Approval was not found.") from exc
    except ApprovalBindingMismatchError as exc:
        raise ApiError(
            409, "approval_binding_mismatch", "Approval binding does not match."
        ) from exc
    except ApprovalExpiredError as exc:
        raise ApiError(409, "approval_expired", "Approval has expired.") from exc
    except ApprovalStateConflictError as exc:
        raise ApiError(
            409, "approval_state_conflict", "Approval is not in a compatible state."
        ) from exc
    except RepositoryConflictError as exc:
        raise ApiError(
            409, "state_conflict", "Persisted approval state changed.", retryable=True
        ) from exc
    except IntegrityError as exc:
        raise ApiError(
            409, "persistence_conflict", "Approval decision could not be persisted."
        ) from exc
    except SQLAlchemyError as exc:
        raise ApiError(
            503, "database_unavailable", "Database is unavailable.", retryable=True
        ) from exc
    return HumanApprovalDecisionResponse(
        approval=result.approval,
        decision=result.decision,
        evaluated_at=result.evaluated_at,
        replayed=result.replayed,
        audit_event_id=result.audit_event_id,
    )
