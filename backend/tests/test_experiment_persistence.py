from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.database import get_session
from app.main import app
from app.models import Experiment


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
    assert run["scenario"] == "normal" and run["fault_injected"] is False
    assert run["model_name"] is None
    assert run["trace_id"] is None
    assert run["evaluation"]["verdict"] == "passed"
    assert run["evaluation"]["evaluator_version"] == "refund-ledger-v1"
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
    # The business action succeeded even though the driver failed before answering.
    assert run["evaluation"]["verdict"] == "passed"
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


@pytest.mark.parametrize("failed,mode", [(False, "demo"), (True, "demo"), (False, "demo_claim_only")])
def test_trace_id_links_saved_run_to_root_span(client, monkeypatch, failed, mode):
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
        run = client.post(path, json={"mode": mode}).json()
        root = next(item for item in exporter.get_finished_spans() if item.name == "agent.run")
        assert run["trace_id"] == f"{root.context.trace_id:032x}"
        assert root.attributes["agent.run_id"] == run["id"]
        assert root.attributes["agent.experiment_id"] == experiment["id"]
        assert root.status.status_code == (StatusCode.ERROR if failed else StatusCode.OK)
        assert run["status"] == ("failed" if failed else "completed")
        assert root.attributes["agent.evaluation.verdict"] == ("failed" if failed or mode == "demo_claim_only" else "passed")
        evaluation_span = next(item for item in exporter.get_finished_spans() if item.name == "evaluation.refund")
        assert evaluation_span.parent.span_id == root.context.span_id
        assert evaluation_span.attributes["openinference.span.kind"] == "EVALUATOR"
        assert evaluation_span.status.status_code == StatusCode.OK
        recovery_span = next(item for item in exporter.get_finished_spans() if item.name == "evaluation.recovery")
        assert recovery_span.parent.span_id == root.context.span_id
        assert recovery_span.attributes["openinference.span.kind"] == "EVALUATOR"
        assert root.attributes["agent.recovery.verdict"] == "not_applicable"
        assert run["recovery_evaluation"]["verdict"] == "not_applicable"
        assert client.get(path).json()[0]["trace_id"] == run["trace_id"]
    finally:
        provider.shutdown()


def test_claim_only_mode_saves_failed_verdict_without_changing_execution_status(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    experiment = client.post("/experiments", json=draft("Claim-only negative control")).json()
    path = f'/experiments/{experiment["id"]}/runs'
    assert client.post(path, json={"mode": "demo_claim_only", "evaluation": {"verdict": "passed"}}).status_code == 422
    assert client.get(path).json() == []
    response = client.post(path, json={"mode": "demo_claim_only"})
    assert response.status_code == 201
    run = response.json()
    assert run["mode"] == "demo_claim_only" and run["model_name"] is None
    assert run["status"] == "completed"
    assert run["evaluation"]["verdict"] == "failed"
    assert run["evaluation"]["observed"]["refunded_cents"] == 0
    assert client.get(path).json()[0] == run
    assert client.get(f'/experiments/{experiment["id"]}').json()["status"] == "completed"


def test_historical_run_is_not_silently_evaluated(client, database_connection):
    from app.agent import TASK
    from app.models import AgentRun
    from app.tools import RefundSandbox
    experiment = client.post("/experiments", json=draft("Historical evidence")).json()
    with Session(database_connection, join_transaction_mode="create_savepoint") as session:
        with session.begin():
            state = RefundSandbox().snapshot()
            session.add(AgentRun(experiment_id=experiment["id"], mode="demo", task=TASK,
                                 status="failed", initial_state=state, final_state=state))
    runs = client.get(f'/experiments/{experiment["id"]}/runs').json()
    assert runs[0]["evaluation"] is None
    assert runs[0]["recovery_evaluation"] is None


def test_database_rejects_scalar_evaluation(database_connection):
    from app.agent import TASK
    from app.models import AgentRun
    from app.tools import RefundSandbox
    with Session(database_connection, join_transaction_mode="create_savepoint") as session:
        with pytest.raises(IntegrityError):
            with session.begin():
                experiment = Experiment(**draft())
                session.add(experiment)
                session.flush()
                state = RefundSandbox().snapshot()
                session.add(AgentRun(experiment_id=experiment.id, mode="demo", task=TASK,
                                     status="completed", initial_state=state, final_state=state,
                                     evaluation="passed"))
                session.flush()


def test_evaluator_error_does_not_lose_completed_execution(client, monkeypatch):
    def broken_evaluator(state):
        raise RuntimeError("private diagnostic payload")
    monkeypatch.setattr("app.execution.evaluate_refund", broken_evaluator)
    experiment = client.post("/experiments", json=draft("Evaluator outage")).json()
    path = f'/experiments/{experiment["id"]}/runs'
    response = client.post(path, json={})
    assert response.status_code == 201
    run = response.json()
    assert run["status"] == "completed"
    assert run["final_state"]["refunded_cents"] == 4900
    assert run["evaluation"]["verdict"] == "not_evaluable"
    assert "private" not in str(run["evaluation"])
    assert client.get(path).json()[0] == run


@pytest.mark.parametrize("mode,status,verdict,injected", [
    ("demo", "failed", "passed", True),
    ("demo_reconcile", "completed", "passed", True),
    ("demo_claim_only", "completed", "failed", False),
])
def test_timeout_scenario_persists_execution_fault_and_evaluation(client, mode, status, verdict, injected):
    experiment = client.post("/experiments", json=draft("Timeout comparison") | {"scenarios": ["timeout_after_commit"]}).json()
    path = f'/experiments/{experiment["id"]}/runs'
    assert client.post(path, json={"mode": mode, "scenario": "normal"}).status_code == 422
    response = client.post(path, json={"mode": mode})
    assert response.status_code == 201
    run = response.json()
    assert run["scenario"] == "timeout_after_commit"
    assert run["status"] == status and run["evaluation"]["verdict"] == verdict
    assert run["fault_injected"] is injected
    assert run["recovery_evaluation"]["verdict"] == {
        "demo": "failed", "demo_reconcile": "passed", "demo_claim_only": "not_evaluable",
    }[mode]
    assert client.get(path).json()[0] == run
    assert client.get(f'/experiments/{experiment["id"]}').json()["status"] == status
    if mode == "demo_reconcile":
        assert [step.get("tool", step["kind"]) for step in run["steps"]] == ["get_order", "issue_refund", "get_order", "answer"]
        assert len(run["final_state"]["refunds"]) == 1
        rerun = client.post(path, json={"mode": mode}).json()
        assert rerun["id"] != run["id"] and rerun["fault_injected"] is True
        assert rerun["initial_state"]["refunds"] == []


@pytest.mark.parametrize("changes", [{"scenario": "unsupported"}, {"scenario": "normal", "fault_injected": True}])
def test_database_rejects_inconsistent_fault_metadata(database_connection, changes):
    from app.agent import TASK
    from app.models import AgentRun
    from app.tools import RefundSandbox
    with Session(database_connection, join_transaction_mode="create_savepoint") as session:
        with pytest.raises(IntegrityError):
            with session.begin():
                experiment = Experiment(**draft())
                session.add(experiment)
                session.flush()
                state = RefundSandbox().snapshot()
                session.add(AgentRun(experiment_id=experiment.id, mode="demo", task=TASK,
                                     status="failed", initial_state=state, final_state=state, **changes))
                session.flush()


@pytest.mark.parametrize("mode,scenario", [("demo", "timeout_after_commit"), ("demo_reconcile", "normal")])
def test_downgrade_refuses_to_erase_fault_or_recovery_history(test_engine, mode, scenario):
    from sqlalchemy import insert, select, text
    from app.agent import TASK
    from app.models import AgentRun
    from app.tools import RefundSandbox

    with test_engine.connect() as connection:
        transaction = connection.begin()
        try:
            experiment_id, run_id = uuid4(), uuid4()
            connection.execute(insert(Experiment).values(id=experiment_id, **draft("Retained evidence")))
            state = RefundSandbox().snapshot()
            connection.execute(insert(AgentRun).values(
                id=run_id, experiment_id=experiment_id, mode=mode, scenario=scenario,
                fault_injected=scenario == "timeout_after_commit", status="failed", task=TASK,
                initial_state=state, final_state=state,
            ))
            config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            config.attributes["connection"] = connection
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    command.downgrade(config, "f348e0530e98")
            assert connection.scalar(select(AgentRun.scenario).where(AgentRun.id == run_id)) == scenario
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "cf13a9502ab7"
        finally:
            transaction.rollback()


@pytest.mark.parametrize("mode,status,policy,injected", [
    ("demo", "failed", "failed", True),
    ("demo_reconcile", "completed", "passed", True),
    ("demo_claim_only", "completed", "not_evaluable", False),
])
def test_permission_results_are_saved_independently(client, mode, status, policy, injected):
    experiment = client.post("/experiments", json=draft("Permission comparison") | {"scenarios": ["permission_denied"]}).json()
    path = f'/experiments/{experiment["id"]}/runs'
    assert client.post(path, json={"mode": mode, "recovery_evaluation": {"verdict": "passed"}}).status_code == 422
    response = client.post(path, json={"mode": mode})
    assert response.status_code == 201
    run = response.json()
    assert run["scenario"] == "permission_denied" and run["fault_injected"] is injected
    assert run["status"] == status
    assert run["evaluation"]["verdict"] == "failed"
    assert run["recovery_evaluation"]["verdict"] == policy
    assert run["recovery_evaluation"]["evaluator_version"] == "recovery-policy-v1"
    assert run["initial_state"] == run["final_state"]
    assert client.get(path).json()[0] == run


def test_recovery_evaluator_failure_preserves_execution_and_ledger(client, monkeypatch):
    def broken(**kwargs):
        raise RuntimeError("private policy diagnostic")
    monkeypatch.setattr("app.execution.evaluate_recovery", broken)
    experiment = client.post("/experiments", json=draft("Recovery evaluator outage")).json()
    path = f'/experiments/{experiment["id"]}/runs'
    run = client.post(path, json={"mode": "demo"}).json()
    assert run["status"] == "completed" and run["evaluation"]["verdict"] == "passed"
    assert run["recovery_evaluation"]["verdict"] == "not_evaluable"
    assert "private" not in str(run["recovery_evaluation"])
    assert client.get(path).json()[0] == run


def test_database_rejects_scalar_recovery_grade(database_connection):
    from app.models import AgentRun
    from app.tools import RefundSandbox
    with Session(database_connection, join_transaction_mode="create_savepoint") as session:
        with pytest.raises(IntegrityError), session.begin():
            experiment = Experiment(**draft())
            session.add(experiment)
            session.flush()
            state = RefundSandbox().snapshot()
            session.add(AgentRun(experiment_id=experiment.id, mode="demo", task="Refund",
                                 status="completed", initial_state=state, final_state=state,
                                 recovery_evaluation="passed"))
            session.flush()


@pytest.mark.parametrize("scenario,policy", [("permission_denied", None), ("normal", {"verdict": "passed"})])
def test_downgrade_refuses_to_erase_permission_or_policy_evidence(test_engine, scenario, policy):
    from sqlalchemy import insert, text
    from app.models import AgentRun
    from app.tools import RefundSandbox
    with test_engine.connect() as connection:
        transaction = connection.begin()
        try:
            experiment_id = uuid4()
            connection.execute(insert(Experiment).values(id=experiment_id, **draft("Policy history")))
            state = RefundSandbox().snapshot()
            connection.execute(insert(AgentRun).values(
                id=uuid4(), experiment_id=experiment_id, mode="demo", scenario=scenario,
                status="completed", task="Refund", initial_state=state, final_state=state,
                recovery_evaluation=policy,
            ))
            config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            config.attributes["connection"] = connection
            with pytest.raises(IntegrityError), connection.begin_nested():
                command.downgrade(config, "ea25a4b836bf")
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "cf13a9502ab7"
        finally:
            transaction.rollback()


def test_empty_policy_migration_round_trip(test_engine):
    from sqlalchemy import text
    # Test database only; transaction rollback retains the suite's schema even on failure.
    assert test_engine.url.database.endswith("_test")
    with test_engine.connect() as connection:
        transaction = connection.begin()
        try:
            assert connection.scalar(text("SELECT count(*) FROM agent_runs")) == 0
            config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            config.attributes["connection"] = connection
            command.downgrade(config, "ea25a4b836bf")
            command.upgrade(config, "head")
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "cf13a9502ab7"
        finally:
            transaction.rollback()
