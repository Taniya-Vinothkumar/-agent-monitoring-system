"""Shared fixtures. Tests never touch the real database or data/ folder."""
import json
from pathlib import Path

import pytest

SAMPLES = Path(__file__).resolve().parents[1] / "shared" / "sample_data"


def load_sample(name: str) -> dict:
    return json.loads((SAMPLES / name).read_text(encoding="utf-8"))


@pytest.fixture
def client():
    # Imported here so reviewer-only tests do not need FastAPI/SQLAlchemy installed.
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from backend.app.config import Settings, get_settings
    from backend.app.database import models  # noqa: F401
    from backend.app.database.connection import Base, get_session
    from backend.app.main import create_app

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, persist_json_files=False)
    return TestClient(app)  # no `with`: skips the lifespan, so init_db() is never run on the real DB
