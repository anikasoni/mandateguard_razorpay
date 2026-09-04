"""Top-level API router."""

from fastapi import APIRouter

from mandateguard.api.routes.health import router as health_router
from mandateguard.api.routes.human_approvals import router as human_approvals_router
from mandateguard.api.routes.policy import router as policy_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(policy_router)
api_router.include_router(human_approvals_router)
