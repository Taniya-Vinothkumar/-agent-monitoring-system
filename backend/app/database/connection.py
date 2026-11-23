"""Database connection (Person 1). STATUS: REAL.

SQLite by default; set DATABASE_URL to use another SQLAlchemy URL.
"""
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    return create_engine(url, **kwargs)


_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = make_engine(get_settings().database_url)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def init_db() -> None:
    """Create tables if they do not exist."""
    from backend.app.database import models  # noqa: F401  (registers tables on Base)

    engine = get_engine()
    if engine.url.get_backend_name() == "sqlite" and engine.url.database:
        from pathlib import Path

        Path(engine.url.database).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    """FastAPI dependency. Tests override this with an in-memory session."""
    get_engine()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()
