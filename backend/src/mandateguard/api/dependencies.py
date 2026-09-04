"""Shared API dependencies for service construction, time, and human trust."""

import secrets
from datetime import datetime
from typing import Annotated, cast

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader

from mandateguard.api.errors import ApiError
from mandateguard.core.config import Settings
from mandateguard.core.time import utc_now
from mandateguard.db.session import SessionFactory
from mandateguard.services.approvals import HumanApprovalService
from mandateguard.services.policy import PolicyService

_HUMAN_KEY = APIKeyHeader(name="X-MandateGuard-Human-Key", auto_error=False)


def get_evaluated_at() -> datetime:
    return utc_now()


def require_json_content_type(request: Request) -> None:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json" and not content_type.endswith("+json"):
        raise ApiError(
            415,
            "unsupported_media_type",
            "Request content type must be application/json.",
        )


def get_settings_from_app(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_session_factory(request: Request) -> SessionFactory:
    try:
        return cast(SessionFactory, request.app.state.database_session_factory)
    except AttributeError as exc:
        raise RuntimeError("application database session factory is not initialized") from exc


def get_policy_service(
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> PolicyService:
    return PolicyService(session_factory, settings)


def get_human_approval_service(
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> HumanApprovalService:
    return HumanApprovalService(session_factory)


def require_human_key(
    supplied: Annotated[str | None, Depends(_HUMAN_KEY)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> None:
    configured = settings.human_approval_key
    if configured is None:
        raise ApiError(
            503,
            "human_approval_unavailable",
            "Human approval is not configured.",
        )
    expected = configured.get_secret_value()
    if supplied is None or not secrets.compare_digest(supplied, expected):
        raise ApiError(
            401,
            "human_authentication_required",
            "Valid human approval credentials are required.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
