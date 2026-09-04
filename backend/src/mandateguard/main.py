"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mandateguard.api.errors import install_error_handlers
from mandateguard.api.router import api_router
from mandateguard.core.config import Settings, get_settings
from mandateguard.core.logging import configure_logging
from mandateguard.db.session import create_database_engine, create_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Release shared resources when the process stops."""

    try:
        yield
    finally:
        app.state.database_engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create a configured MandateGuard API instance."""

    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)

    application = FastAPI(
        title="MandateGuard API",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    database_engine = create_database_engine(resolved_settings.database_url)
    application.state.database_engine = database_engine
    application.state.database_session_factory = create_session_factory(database_engine)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-MandateGuard-Human-Key"],
    )
    install_error_handlers(application)
    application.include_router(api_router, prefix="/api/v1")
    return application


app = create_app()
