"""Process and database health endpoints."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from mandateguard.core.time import utc_now
from mandateguard.db.session import get_engine

router = APIRouter(prefix="/health", tags=["health"])


class LiveResponse(BaseModel):
    """Liveness response contract."""

    status: Literal["ok"]
    service: Literal["mandateguard-api"]
    timestamp: datetime


class ReadyResponse(BaseModel):
    """Readiness response contract."""

    status: Literal["ready"]
    service: Literal["mandateguard-api"]
    database: Literal["ok"]
    timestamp: datetime


@router.get("/live", response_model=LiveResponse)
def live() -> LiveResponse:
    """Report that the API process can serve requests."""

    return LiveResponse(status="ok", service="mandateguard-api", timestamp=utc_now())


@router.get("/ready", response_model=ReadyResponse)
def ready(engine: Annotated[Engine, Depends(get_engine)]) -> ReadyResponse:
    """Report readiness after verifying a database round trip."""

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc

    return ReadyResponse(
        status="ready",
        service="mandateguard-api",
        database="ok",
        timestamp=utc_now(),
    )
