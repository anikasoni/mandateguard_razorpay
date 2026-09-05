"""Production-like startup and frontend-serving tests."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mandateguard.core.config import Settings
from mandateguard.core.startup import ensure_database_directory
from mandateguard.main import create_app


def _frontend_build(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(
        '<!doctype html><html><body><div id="root">production-spa</div></body></html>',
        encoding="utf-8",
    )
    (assets / "app-test.js").write_text("globalThis.mandateGuardLoaded = true", encoding="utf-8")
    return dist


def test_built_frontend_serves_root_browser_routes_and_assets(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            _env_file=None,
            environment="production",
            database_url="sqlite+pysqlite:///:memory:",
            frontend_dist_dir=_frontend_build(tmp_path),
        )
    )

    with TestClient(app) as client:
        root = client.get("/")
        browser_route = client.get("/demo/checkout", headers={"Accept": "text/html"})
        asset = client.get("/assets/app-test.js")
        missing_asset = client.get("/assets/missing.js")

    assert (root.status_code, "production-spa" in root.text) == (200, True)
    assert (browser_route.status_code, "production-spa" in browser_route.text) == (200, True)
    assert asset.status_code == 200
    assert asset.headers["content-type"].startswith("text/javascript")
    assert missing_asset.status_code == 404
    assert "production-spa" not in missing_asset.text


@pytest.mark.parametrize("path", ["/api", "/api/unknown", "/api/v1/unknown"])
def test_unknown_api_gets_json_404_not_spa(tmp_path: Path, path: str) -> None:
    app = create_app(
        Settings(
            _env_file=None,
            environment="production",
            database_url="sqlite+pysqlite:///:memory:",
            frontend_dist_dir=_frontend_build(tmp_path),
        )
    )

    with TestClient(app) as client:
        response = client.get(path, headers={"Accept": "text/html"})

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "Not Found"}
    assert "production-spa" not in response.text


def test_non_browser_unknown_route_is_not_rewritten(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            _env_file=None,
            environment="production",
            database_url="sqlite+pysqlite:///:memory:",
            frontend_dist_dir=_frontend_build(tmp_path),
        )
    )

    with TestClient(app) as client:
        response = client.get("/machine-route", headers={"Accept": "application/json"})
        wildcard_response = client.get("/wildcard-route")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert wildcard_response.status_code == 404
    assert wildcard_response.headers["content-type"].startswith("application/json")


def test_startup_creates_nested_sqlite_directory(tmp_path: Path) -> None:
    database_path = tmp_path / "mounted" / "nested" / "mandateguard.db"
    settings = Settings(
        _env_file=None,
        environment="production",
        database_url=f"sqlite:///{database_path.as_posix()}",
    )

    ensure_database_directory(settings)
    ensure_database_directory(settings)

    assert database_path.parent.is_dir()
    assert not database_path.exists()


def test_railway_sqlite_url_and_start_script_configuration() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        database_url="sqlite:////data/mandateguard.db",
    )
    script = Path("scripts/start.sh").read_text(encoding="utf-8")

    assert settings.database_url == "sqlite:////data/mandateguard.db"
    assert "set -eu" in script
    assert script.index("alembic -c /app/backend/alembic.ini upgrade head") < script.index(
        "python -m mandateguard.demo.seed"
    )
    assert 'exec uvicorn mandateguard.main:app --host 0.0.0.0 --port "$PORT" --workers 1' in script
    assert "--reload" not in script
    assert "printenv" not in script
    assert "set -x" not in script


def test_production_app_initialization_does_not_call_external_providers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_network_call(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("startup attempted an external provider call")

    monkeypatch.setattr("mandateguard.agent.planner.urlopen", unexpected_network_call)
    monkeypatch.setattr("mandateguard.integrations.razorpay.urlopen", unexpected_network_call)
    settings = Settings(
        _env_file=None,
        environment="production",
        database_url="sqlite+pysqlite:///:memory:",
        frontend_dist_dir=_frontend_build(tmp_path),
        gemini_api_key="placeholder-gemini-key",
        gemini_model="gemini-placeholder-model",
        razorpay_key_id="rzp_test_placeholder",
        razorpay_key_secret="placeholder-secret",
        human_approval_key="placeholder-human-key",
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
