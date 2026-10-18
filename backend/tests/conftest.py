import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.database import get_session
from app.main import app


@pytest.fixture(scope="module")
def test_engine():
    url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://agent_autopsy:agent_autopsy@127.0.0.1:55432/agent_autopsy_test",
    )
    assert make_url(url).database.endswith("_test"), "Use a dedicated _test database"
    engine = create_engine(url, connect_args={"connect_timeout": 3})
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def database_connection(test_engine):
    with test_engine.connect() as connection:
        transaction = connection.begin()
        yield connection
        transaction.rollback()


@pytest.fixture
def api_client(database_connection):
    def override_session():
        with Session(
            database_connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def client(api_client, monkeypatch):
    """Existing inline-engine integration tests explicitly enable the legacy HTTP adapter.

    Queue/API-boundary tests use api_client, which retains production defaults.
    """
    monkeypatch.setenv("AGENT_AUTOPSY_SYNC_API_ENABLED", "true")
    return api_client
