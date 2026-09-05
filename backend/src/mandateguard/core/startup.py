"""Small startup helpers shared by deployment scripts and tests."""

from pathlib import Path

from sqlalchemy.engine import make_url

from mandateguard.core.config import Settings, get_settings


def ensure_database_directory(settings: Settings | None = None) -> None:
    """Create the parent directory for a configured file-backed SQLite database."""

    database_url = make_url((settings or get_settings()).database_url)
    if database_url.get_backend_name() != "sqlite":
        return

    database_path = database_url.database
    if database_path is None or database_path == ":memory:":
        return
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)


def main() -> None:
    ensure_database_directory()


if __name__ == "__main__":
    main()
