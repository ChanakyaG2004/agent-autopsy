from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from pathlib import Path
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.benchmark import read_benchmark, run_benchmark, summarize
from app.benchmark_schemas import BenchmarkRequest
from app.benchmark_suite import build_manifest, digest, suite_definition
from app.models import AgentRun, Benchmark, BenchmarkItem, Experiment


def test_suite_is_honest_about_distinct_task_and_scripted_drivers(client):
    suites = client.get("/benchmark-suites").json()
    assert suites == [suite_definition()]
    assert suites[0]["distinct_tasks"] == 1
    assert len(suites[0]["cases"]) == 3
    assert suites[0]["drivers"] == ["demo", "demo_reconcile", "demo_claim_only"]


def test_manifest_is_stable_and_captures_relevant_configuration(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "private-key-never-snapshot")
    first, second = build_manifest(1, "test-schema"), build_manifest(1, "test-schema")
    assert first == second
    assert first["suite_digest"] == digest(first["suite"])
    assert len(first["schedule"]) == 9
    assert len(build_manifest(3, "test-schema")["schedule"]) == 27
    assert first["configuration"]["model"] is None
    assert first["configuration"]["max_turns"] == 6
    assert first["source"]["files"]["app/agent.py"]
    assert first["source"]["files"]["uv.lock"]
    assert first["environment"]["schema_revision"] == "test-schema"
    assert "private-key" not in str(first)
    first["configuration"]["tool_schemas"].clear()
    assert build_manifest(1, "test-schema")["configuration"]["tool_schemas"]


def test_missing_item_rows_cannot_shrink_the_planned_denominator():
    summary = summarize(build_manifest(1, "test-schema"), [])
    assert summary.overall.planned == summary.overall.infrastructure_failed == 9
    assert summary.overall.recorded == 0 and summary.overall.fault_selected == 6
    assert all(group.counts.planned == 3 for group in summary.drivers)


@pytest.mark.parametrize("body", [
    {"repetitions": 0}, {"repetitions": 4}, {"repetitions": True}, {"repetitions": "2"},
    {"suite_version": "unknown"}, {"mode": "openai"}, {"summary": {"ledger_passed": 9}},
])
def test_invalid_configuration_cannot_write_a_benchmark(client, body):
    assert client.post("/benchmarks", json=body).status_code == 422
    assert client.get("/benchmarks").json() == []
    assert client.get("/experiments").json() == []


def test_full_matrix_preserves_independent_outcomes_and_trace_links(client, monkeypatch):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from app import telemetry
    exporter = InMemorySpanExporter()
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry, "_provider", provider)
    try:
        response = client.post("/benchmarks", json={})
        assert response.status_code == 201
        report = response.json()
        assert report["status"] == "completed" and report["finished_at"]
        assert len(report["items"]) == 9
        assert report["manifest"]["suite"]["distinct_tasks"] == 1
        assert [item["position"] for item in report["items"]] == list(range(9))
        counts = report["summary"]["overall"]
        assert counts == dict(planned=9, recorded=9, infrastructure_failed=0, pending=0,
                              execution_completed=7, execution_failed=2, ledger_passed=4, ledger_failed=5,
                              ledger_not_evaluable=0, recovery_passed=2, recovery_failed=2,
                              recovery_not_evaluable=2, recovery_not_applicable=3, fault_selected=6, fault_injected=4)
        grouped = {group["mode"]: group["counts"] for group in report["summary"]["drivers"]}
        assert grouped["demo"]["recovery_failed"] == 2
        assert grouped["demo_reconcile"]["recovery_passed"] == 2
        assert grouped["demo_claim_only"]["fault_injected"] == 0
        roots = {f"{span.context.trace_id:032x}": span for span in exporter.get_finished_spans()
                 if span.name == "agent.run"}
        assert len(roots) == 9
        for item in report["items"]:
            assert item["status"] == "completed"
            assert item["id"] == item["run_id"] == item["run"]["id"]
            assert item["experiment_id"] == item["run"]["experiment_id"]
            assert item["run"]["initial_state"]["refunds"] == []
            assert item["run"]["trace_id"] in roots
        # Read returns the original frozen summary and manifest, even if current suite code changes.
        monkeypatch.setattr("app.benchmark_suite.TASK", "Different future task")
        assert client.get(f'/benchmarks/{report["id"]}').json() == report
        listed = client.get("/benchmarks").json()
        assert listed[0]["summary"] == report["summary"] and "manifest" not in listed[0]
    finally:
        provider.shutdown()


def test_repetitions_scale_counts_without_leaking_order_state(client):
    report = client.post("/benchmarks", json={"repetitions": 2}).json()
    counts = report["summary"]["overall"]
    assert counts["planned"] == counts["recorded"] == 18
    assert counts["ledger_passed"] == 8 and counts["fault_selected"] == 12
    assert counts["fault_injected"] == 8
    assert {item["repetition"] for item in report["items"]} == {1, 2}
    assert len({item["run_id"] for item in report["items"]}) == 18
    assert all(item["run"]["initial_state"]["refunds"] == [] for item in report["items"])


def test_execution_has_no_suite_transaction_and_initial_schedule_is_saved(client, monkeypatch):
    from app.execution import start_run
    seen = []
    def observe(experiment_id, mode, session, **kwargs):
        assert not session.in_transaction()
        with session.begin():
            assert session.scalar(select(func.count()).select_from(BenchmarkItem)) == 9
            benchmark = session.scalar(select(Benchmark))
            assert benchmark.status == "running" and benchmark.finished_at is None
            assert benchmark.summary["overall"]["planned"] == 9
        seen.append(kwargs["run_id"])
        return start_run(experiment_id, mode, session, **kwargs)
    monkeypatch.setattr("app.benchmark.start_run", observe)
    report = client.post("/benchmarks", json={}).json()
    assert report["status"] == "completed" and len(seen) == 9


def test_schedule_is_visible_from_another_connection_while_agent_is_blocked(test_engine, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from sqlalchemy import delete
    from app.execution import start_run
    from app.providers import make_driver

    entered, release = Event(), Event()
    context = {}

    def capture(experiment_id, mode, session, **kwargs):
        assert not session.in_transaction()
        with session.begin():
            item = session.get(BenchmarkItem, kwargs["run_id"])
            context["benchmark_id"] = item.benchmark_id
        context["session"] = session
        return start_run(experiment_id, mode, session, **kwargs)

    class BlockedDriver:
        def __init__(self, delegate):
            self.delegate = delegate

        def decide(self, history):
            assert not context["session"].in_transaction()
            if not entered.is_set():
                entered.set()
                assert release.wait(5)
            return self.delegate.decide(history)

    monkeypatch.setattr("app.benchmark.start_run", capture)
    monkeypatch.setattr("app.execution.make_driver", lambda mode: (BlockedDriver(make_driver(mode)[0]), None))

    def work():
        with Session(test_engine, expire_on_commit=False) as session:
            return run_benchmark(BenchmarkRequest(), session)

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(work)
            try:
                assert entered.wait(5)
                with Session(test_engine) as session:
                    benchmark = session.get(Benchmark, context["benchmark_id"])
                    assert benchmark.status == "running"
                    assert benchmark.summary["overall"]["planned"] == 9
                    statuses = list(session.scalars(select(BenchmarkItem.status)
                                                    .where(BenchmarkItem.benchmark_id == benchmark.id)))
                    assert statuses.count("pending") == 8 and statuses.count("running") == 1
            finally:
                release.set()
            benchmark_id = future.result(timeout=5)
        with Session(test_engine) as session:
            assert session.get(Benchmark, benchmark_id).summary["overall"]["recorded"] == 9
    finally:
        if "benchmark_id" in context:
            with test_engine.begin() as connection:
                experiment_ids = list(connection.scalars(select(BenchmarkItem.experiment_id)
                                                        .where(BenchmarkItem.benchmark_id == context["benchmark_id"])))
                connection.execute(delete(BenchmarkItem).where(BenchmarkItem.benchmark_id == context["benchmark_id"]))
                connection.execute(delete(AgentRun).where(AgentRun.experiment_id.in_(experiment_ids)))
                connection.execute(delete(Experiment).where(Experiment.id.in_(experiment_ids)))
                connection.execute(delete(Benchmark).where(Benchmark.id == context["benchmark_id"]))


def test_infrastructure_failure_stays_in_denominators_and_other_items_continue(client, monkeypatch):
    from app.execution import start_run
    calls = 0
    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("private provider diagnostics")
        return start_run(*args, **kwargs)
    monkeypatch.setattr("app.benchmark.start_run", fail_once)
    report = client.post("/benchmarks", json={}).json()
    assert calls == 9 and report["status"] == "failed"
    assert report["summary"]["overall"]["planned"] == 9
    assert report["summary"]["overall"]["recorded"] == 8
    assert report["summary"]["overall"]["infrastructure_failed"] == 1
    assert report["summary"]["overall"]["pending"] == 0
    missing = report["items"][1]
    assert missing["status"] == "failed" and missing["run"] is None
    assert "private" not in str(report)
    assert client.get(f'/benchmarks/{report["id"]}').json() == report


def test_late_exception_recovers_terminal_result_without_retrying(client, monkeypatch):
    from app.execution import start_run
    calls = 0
    def late_failure(*args, **kwargs):
        nonlocal calls
        calls += 1
        start_run(*args, **kwargs)
        raise RuntimeError("private cleanup exception")
    monkeypatch.setattr("app.benchmark.start_run", late_failure)
    report = client.post("/benchmarks", json={}).json()
    assert calls == 9 and report["status"] == "completed"
    assert report["summary"]["overall"]["recorded"] == 9
    assert all(item["error"] and item["run"] for item in report["items"])
    assert "private" not in str(report)


def test_evaluator_outage_remains_unavailable_in_aggregate(client, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("unavailable")
    monkeypatch.setattr("app.execution.evaluate_recovery", broken)
    report = client.post("/benchmarks", json={}).json()
    counts = report["summary"]["overall"]
    assert report["status"] == "completed"
    assert counts["ledger_passed"] == 4
    assert counts["recovery_passed"] == counts["recovery_failed"] == 0
    assert counts["recovery_not_evaluable"] == 9


def test_get_missing_and_bounded_pagination(client):
    assert client.get(f"/benchmarks/{uuid4()}").status_code == 404
    assert client.get("/benchmarks/no-uuid").status_code == 422
    for query in ("limit=0", "limit=101", "offset=-1"):
        assert client.get(f"/benchmarks?{query}").status_code == 422
    first = client.post("/benchmarks", json={}).json()
    second = client.post("/benchmarks", json={}).json()
    expected = sorted([first, second], key=lambda b: (b["started_at"], b["id"]), reverse=True)
    listed = client.get("/benchmarks?limit=1&offset=1").json()
    assert listed[0]["id"] == expected[1]["id"]


def test_default_expiring_session_is_supported(database_connection):
    with Session(database_connection, join_transaction_mode="create_savepoint") as session:
        benchmark_id = run_benchmark(BenchmarkRequest(), session)
        assert read_benchmark(benchmark_id, session).summary.overall.recorded == 9


def test_persisted_running_execution_is_retained_after_interruption(client, monkeypatch):
    from app.agent import TASK
    from app.tools import RefundSandbox
    def interrupted(experiment_id, mode, session, *, run_id):
        with session.begin():
            state = RefundSandbox().snapshot()
            session.add(AgentRun(id=run_id, experiment_id=experiment_id, mode=mode, task=TASK,
                                 status="running", initial_state=state, final_state=state))
        raise RuntimeError("worker interruption")
    monkeypatch.setattr("app.benchmark.start_run", interrupted)
    report = client.post("/benchmarks", json={}).json()
    assert report["status"] == "failed"
    assert report["summary"]["overall"]["infrastructure_failed"] == 9
    assert report["summary"]["overall"]["recorded"] == 0
    assert all(item["run"]["status"] == "running" for item in report["items"])


def test_downgrade_refuses_to_discard_benchmark_history(client, database_connection):
    report = client.post("/benchmarks", json={}).json()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["connection"] = database_connection
    with pytest.raises(IntegrityError), database_connection.begin_nested():
        command.downgrade(config, "c0b22d930094")
    assert database_connection.scalar(text("SELECT version_num FROM alembic_version")) == "cf13a9502ab7"
    assert client.get(f'/benchmarks/{report["id"]}').json() == report


@pytest.mark.parametrize("changes", [
    {"mode": "openai"}, {"repetition": 0}, {"position": -1}, {"status": "completed"},
    {"status": "unknown"},
])
def test_database_rejects_invalid_scheduled_items(database_connection, changes):
    with Session(database_connection, join_transaction_mode="create_savepoint") as session:
        with pytest.raises(IntegrityError), session.begin():
            benchmark = Benchmark(suite_version="test", status="running", manifest={}, summary={})
            experiment = Experiment(name="Constraint test", agent_version="refund-v1", scenarios=["normal"])
            session.add_all([benchmark, experiment])
            session.flush()
            values = dict(benchmark_id=benchmark.id, experiment_id=experiment.id, position=0,
                          case_key="normal", mode="demo", repetition=1, status="pending") | changes
            session.add(BenchmarkItem(**values))
            session.flush()
