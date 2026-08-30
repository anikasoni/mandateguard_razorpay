"""Health endpoint tests."""

from datetime import datetime
from pathlib import Path
from typing import Annotated

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from mandateguard.core.config import Settings, get_settings
from mandateguard.db.session import get_engine, get_session
from mandateguard.main import create_app


class BrokenEngine:
    """Engine-shaped test double that always fails its readiness connection."""

    def connect(self) -> None:
        raise SQLAlchemyError("database offline")


def build_test_client(database_url: str = "sqlite+pysqlite:///:memory:") -> TestClient:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        cors_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    )
    return TestClient(create_app(settings))


def test_liveness_response_is_typed_and_utc_aware() -> None:
    with build_test_client() as client:
        response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "mandateguard-api"
    assert datetime.fromisoformat(body["timestamp"]).utcoffset().total_seconds() == 0


def test_readiness_checks_sqlite() -> None:
    with build_test_client() as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json()["database"] == "ok"


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://127.0.0.1:5173"])
def test_local_frontend_origins_receive_cors_headers(origin: str) -> None:
    with build_test_client() as client:
        response = client.get("/api/v1/health/live", headers={"Origin": origin})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert "Origin" in response.headers["vary"]


def test_app_factory_uses_supplied_database_for_readiness_and_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    default_database = tmp_path / "unexpected-default.db"
    alternate_database = tmp_path / "application.db"
    default_url = f"sqlite+pysqlite:///{default_database.as_posix()}"
    alternate_url = f"sqlite+pysqlite:///{alternate_database.as_posix()}"
    monkeypatch.setenv("MANDATEGUARD_DATABASE_URL", default_url)
    get_settings.cache_clear()

    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=alternate_url,
        cors_origins=["http://127.0.0.1:5173"],
    )
    application = create_app(settings)

    @application.get("/_test/session-database")
    def session_database(session: Annotated[Session, Depends(get_session)]) -> dict[str, str]:
        session.execute(text("SELECT 1"))
        return {"database_url": str(session.get_bind().url)}

    with TestClient(application) as client:
        ready_response = client.get("/api/v1/health/ready")
        session_response = client.get("/_test/session-database")

    assert ready_response.status_code == 200
    assert session_response.json() == {"database_url": alternate_url}
    assert alternate_database.exists()
    assert not default_database.exists()


def test_readiness_returns_503_when_database_is_unavailable() -> None:
    app = build_test_client().app
    app.dependency_overrides[get_engine] = lambda: BrokenEngine()  # type: ignore[return-value]

    with TestClient(app) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "database unavailable"}
