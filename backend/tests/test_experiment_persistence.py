import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.database import get_session
from app.main import app
from app.models import Experiment


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
def client(database_connection):
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


def draft(name="Refund baseline"):
    return {"name": name, "agent_version": "refund-v1", "scenarios": ["normal"]}


def test_create_and_retrieve_across_sessions(client):
    response = client.post("/experiments", json=draft("  Refund baseline  "))
    assert response.status_code == 201
    saved = response.json()
    assert saved["name"] == "Refund baseline"
    assert saved["status"] == "draft"
    assert saved["created_at"]
    assert client.get(f'/experiments/{saved["id"]}').json() == saved


def test_list_is_bounded_and_pagination_is_stable(client):
    first = client.post("/experiments", json=draft("First draft")).json()
    second = client.post("/experiments", json=draft("Second draft")).json()
    expected = sorted([first, second], key=lambda item: (item["created_at"], item["id"]), reverse=True)
    assert client.get("/experiments").json() == expected
    assert client.get("/experiments?limit=1&offset=0").json() == expected[:1]
    assert client.get("/experiments?limit=1&offset=1").json() == expected[1:]


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
def test_rejects_invalid_pagination(client, query):
    assert client.get(f"/experiments?{query}").status_code == 422


def test_missing_and_malformed_ids(client):
    assert client.get(f"/experiments/{uuid4()}").status_code == 404
    assert client.get("/experiments/not-a-uuid").status_code == 422


@pytest.mark.parametrize(
    "changes",
    [{"name": "  "}, {"scenarios": ["unknown"]}, {"scenarios": ["normal", "normal"]}],
)
def test_invalid_create_does_not_write(client, changes):
    assert client.post("/experiments", json=draft() | changes).status_code == 422
    assert client.get("/experiments").json() == []


def test_failed_commit_rolls_back_insert(client, database_connection):
    def fail_commit(session):
        raise OperationalError("test commit failure", {}, Exception("simulated"))

    def failing_session():
        with Session(
            database_connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as session:
            event.listen(session, "before_commit", fail_commit, once=True)
            yield session

    original = app.dependency_overrides[get_session]
    app.dependency_overrides[get_session] = failing_session
    try:
        assert client.post("/experiments", json=draft()).status_code == 503
    finally:
        app.dependency_overrides[get_session] = original
    assert client.get("/experiments").json() == []


def test_database_error_has_safe_service_response():
    def unavailable_session():
        raise OperationalError("connection failed", {}, Exception("simulated"))
        yield

    app.dependency_overrides[get_session] = unavailable_session
    try:
        with TestClient(app) as client:
            response = client.get("/experiments")
        assert response.status_code == 503
        assert response.json() == {"detail": "Could not complete the database operation. Try again later."}
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_database_rejects_unsupported_status(database_connection):
    with Session(database_connection, join_transaction_mode="create_savepoint") as session:
        with pytest.raises(IntegrityError):
            with session.begin():
                session.add(Experiment(**draft(), status="running"))
                session.flush()
