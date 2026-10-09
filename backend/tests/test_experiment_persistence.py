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
                session.add(Experiment(**draft(), status="unknown"))
                session.flush()


def test_run_is_persisted_and_experiment_changes_status(client):
    saved = client.post("/experiments", json=draft()).json()
    path = f'/experiments/{saved["id"]}/runs'
    response = client.post(path, json={"mode": "demo"})
    assert response.status_code == 201
    run = response.json()
    assert run["status"] == "completed" and run["mode"] == "demo"
    assert run["model_name"] is None
    assert run["trace_id"] is None
    assert run["final_state"]["refunded_cents"] == 4900
    assert run["finished_at"] is not None
    assert client.get(path).json() == [run]
    assert client.get(f'/experiments/{saved["id"]}').json()["status"] == "completed"
    rerun = client.post(path, json={}).json()
    assert rerun["id"] != run["id"]
    assert rerun["initial_state"]["refunded_cents"] == 0
    assert len(client.get(path + "?limit=1").json()) == 1
    assert client.get(path + "?limit=21").status_code == 422


@pytest.mark.parametrize("changes", [{"scenarios": ["normal", "timeout_after_commit"]}, {"agent_version": "unknown"}])
def test_unsupported_execution_does_not_mutate_experiment(client, changes):
    saved = client.post("/experiments", json=draft() | changes).json()
    path = f'/experiments/{saved["id"]}/runs'
    assert client.post(path, json={}).status_code == 409
    assert client.get(path).json() == []
    assert client.get(f'/experiments/{saved["id"]}').json()["status"] == "draft"


def test_missing_key_does_not_claim_experiment(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    saved = client.post("/experiments", json=draft()).json()
    path = f'/experiments/{saved["id"]}/runs'
    assert client.post(path, json={"mode": "openai"}).status_code == 503
    assert client.get(path).json() == []
    assert client.get(f'/experiments/{saved["id"]}').json()["status"] == "draft"


def test_run_failure_retains_partial_state(client, monkeypatch):
    from app.agent import AgentError, DemoDriver
    class FailingDriver(DemoDriver):
        def decide(self, history):
            if len(history) >= 5:
                raise AgentError("Simulated model failure.")
            return super().decide(history)
    monkeypatch.setattr("app.execution.make_driver", lambda mode: (FailingDriver(), None))
    saved = client.post("/experiments", json=draft()).json()
    path = f'/experiments/{saved["id"]}/runs'
    run = client.post(path, json={}).json()
    assert run["status"] == "failed"
    assert run["final_state"]["refunded_cents"] == 4900
    assert len(run["steps"]) == 2
    assert client.get(path).json()[0]["error"] == "Simulated model failure."
    assert client.get(f'/experiments/{saved["id"]}').json()["status"] == "failed"


def test_run_routes_handle_missing_ids_and_invalid_mode(client):
    path = f"/experiments/{uuid4()}/runs"
    assert client.get(path).status_code == 404
    assert client.post(path, json={}).status_code == 404
    assert client.post(path, json={"mode": "unknown"}).status_code == 422


def test_atomic_claim_blocks_a_second_run(test_engine, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from fastapi import HTTPException
    from sqlalchemy import delete
    from app.agent import DemoDriver
    from app.execution import start_run
    from app.models import AgentRun

    entered, release = Event(), Event()
    active_session = {}
    class BlockingDriver(DemoDriver):
        def decide(self, history):
            assert not active_session["session"].in_transaction()
            entered.set()
            assert release.wait(5)
            return super().decide(history)
    monkeypatch.setattr("app.execution.make_driver", lambda mode: (BlockingDriver(), None))
    with Session(test_engine, expire_on_commit=False) as session:
        experiment = Experiment(**draft("Concurrent run"))
        with session.begin():
            session.add(experiment)
            session.flush()
        experiment_id = experiment.id

    def first_run():
        with Session(test_engine, expire_on_commit=False) as session:
            active_session["session"] = session
            return start_run(experiment_id, "demo", session)

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(first_run)
            try:
                assert entered.wait(5)
                with Session(test_engine, expire_on_commit=False) as session:
                    # The first claim is committed and visible while the model is blocked.
                    assert session.get(Experiment, experiment_id).status == "running"
                    session.rollback()
                    with pytest.raises(HTTPException) as caught:
                        start_run(experiment_id, "demo", session)
                    assert caught.value.status_code == 409
            finally:
                release.set()
            assert future.result(timeout=5).status == "completed"
    finally:
        with test_engine.begin() as connection:
            connection.execute(delete(AgentRun).where(AgentRun.experiment_id == experiment_id))
            connection.execute(delete(Experiment).where(Experiment.id == experiment_id))


@pytest.mark.parametrize("failed", [False, True])
def test_trace_id_links_saved_run_to_root_span(client, monkeypatch, failed):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from app import telemetry
    from app.agent import ModelTurn, ToolCall
    from opentelemetry.trace import StatusCode

    exporter = InMemorySpanExporter()
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry, "_provider", provider)
    if failed:
        class RejectedDriver:
            def decide(self, history):
                return ModelTurn([], [ToolCall("unregistered", {}, "test-call")])
        monkeypatch.setattr("app.execution.make_driver", lambda mode: (RejectedDriver(), None))
    try:
        experiment = client.post("/experiments", json=draft("Traced refund")).json()
        path = f'/experiments/{experiment["id"]}/runs'
        run = client.post(path, json={}).json()
        root = next(item for item in exporter.get_finished_spans() if item.name == "agent.run")
        assert run["trace_id"] == f"{root.context.trace_id:032x}"
        assert root.attributes["agent.run_id"] == run["id"]
        assert root.attributes["agent.experiment_id"] == experiment["id"]
        assert root.status.status_code == (StatusCode.ERROR if failed else StatusCode.OK)
        assert run["status"] == ("failed" if failed else "completed")
        assert client.get(path).json()[0]["trace_id"] == run["trace_id"]
    finally:
        provider.shutdown()
