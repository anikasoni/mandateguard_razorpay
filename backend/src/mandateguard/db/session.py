"""SQLAlchemy engine and session lifecycle."""

from collections.abc import Generator
from typing import cast

from fastapi import Request
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

SessionFactory = sessionmaker[Session]


def create_database_engine(database_url: str) -> Engine:
    """Create an engine with safe SQLite demo defaults when applicable."""

    is_sqlite = database_url.startswith("sqlite")
    connect_args = {"check_same_thread": False} if is_sqlite else {}
    engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)

    if is_sqlite:

        @event.listens_for(engine, "connect")
        def configure_sqlite(dbapi_connection: object, connection_record: object) -> None:
            del connection_record
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=5000")
            finally:
                cursor.close()

    return engine


def create_session_factory(engine: Engine) -> SessionFactory:
    """Create an application-scoped session factory bound to one engine."""

    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_engine(request: Request) -> Engine:
    """Return the engine owned by the current FastAPI application."""

    try:
        return cast(Engine, request.app.state.database_engine)
    except AttributeError as exc:
        raise RuntimeError("application database engine is not initialized") from exc


def get_session(request: Request) -> Generator[Session, None, None]:
    """Yield a session from the current application's session factory."""

    try:
        session_factory = cast(SessionFactory, request.app.state.database_session_factory)
    except AttributeError as exc:
        raise RuntimeError("application database session factory is not initialized") from exc

    with session_factory() as session:
        yield session
