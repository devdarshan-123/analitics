from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

# Configure the app for tests before anything imports app.config.
os.environ.update({
    "MOCK_MODE": "true",
    # The app's own engine (used by the lifespan seed) gets a throwaway file DB.
    "DATABASE_URL": "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"),
    "DASHBOARD_PASSWORD": "test-password",
    "ENABLE_SCHEDULER": "false",
    "CLARITY_API_TOKEN": "",
    "CLARITY_TOKENS": "",
    # Override whatever the developer's .env says, so tests always use the mock property list.
    "GA4_PROPERTY_ID": "",
    "GA_PROPERTY_ALLOWLIST": "",
    "CLARITY_TOKEN_ENCRYPTION_KEY": "dGVzdC1rZXktZm9yLWZlcm5ldC0zMi1ieXRlcyEhISE=",
})

from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

from app.db import init_db  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def clarity_fixture() -> list:
    return json.loads((FIXTURES / "clarity_live_insights.json").read_text(encoding="utf-8"))


@pytest.fixture
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
