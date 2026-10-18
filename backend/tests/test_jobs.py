from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent import DemoDriver
from app.benchmark import read_benchmark
from app.job_schemas import BenchmarkJobRequest, RunJobRequest
from app.jobs import (LeaseLost, claim_next, enqueue_benchmark, enqueue_run, finish_job,
                      heartbeat, recover_expired)
from app.models import AgentRun, Benchmark, BenchmarkItem, Experiment, Job
from app.worker import process_claimed


def experiment(client):
    return client.post("/experiments", json={"name": "Queued experiment", "agent_version": "refund-v1", "scenarios": ["normal"]}).json()["id"]


def test_enqueue_is_fast_read_only_for_providers_and_idempotent_even_at_capacity(api_client, monkeypatch):
    monkeypatch.delenv("AGENT_AUTOPSY_SYNC_API_ENABLED", raising=False)
    monkeypatch.setattr("app.execution.make_driver", lambda *_: pytest.fail("HTTP enqueue must not initialize a provider"))
    monkeypatch.setattr("app.jobs.QUEUE_CAPACITY", 1)
    first, other = experiment(api_client), experiment(api_client)
    body = {"mode": "demo", "request_id": str(uuid4())}
    path = f"/experiments/{first}/jobs"
    response = api_client.post(path, json=body)
    assert response.status_code == 202
    job = response.json()
    assert job["status"] == "queued" and job["attempts"] == 0 and job["run_id"]
    assert "lease_token" not in job and "payload" not in job and "execution_fingerprint" not in job
    assert api_client.post(path, json=body).json() == job
    assert api_client.post(path, json=body | {"mode": "ollama"}).status_code == 409
    assert api_client.post(path, json=body | {"request_id": str(uuid4())}).status_code == 429
    assert api_client.post(f"/experiments/{other}/jobs", json=body | {"request_id": str(uuid4())}).status_code == 429
    assert api_client.get(f"/experiments/{first}/runs").json() == []
    assert api_client.get(f'/jobs/{job["id"]}').json() == job
    assert api_client.get(f"/jobs?experiment_id={first}&limit=1").json() == [job]
    assert api_client.post(f"/experiments/{first}/runs", json={"mode": "demo"}).status_code == 410
    assert api_client.post("/benchmarks", json={}).status_code == 410


def test_active_reservation_and_request_key_reuse_cannot_create_other_work(api_client):
    first, second = experiment(api_client), experiment(api_client)
    body = {"mode": "demo", "request_id": str(uuid4())}
    assert api_client.post(f"/experiments/{first}/jobs", json=body).status_code == 202
    assert api_client.post(f"/experiments/{first}/jobs", json=body | {"request_id": str(uuid4())}).status_code == 409
    assert api_client.post(f"/experiments/{second}/jobs", json=body).status_code == 409
    assert api_client.post("/benchmark-jobs", json={"request_id": body["request_id"]}).status_code == 409
    for query in ("limit=0", "limit=101", "offset=-1", "kind=bad"):
        assert api_client.get(f"/jobs?{query}").status_code == 422
    assert api_client.get(f"/jobs/{uuid4()}").status_code == 404


@pytest.mark.parametrize("extra", [{}, {"request_id": "bad"}, {"request_id": str(uuid4()), "mode": "shell"},
                                    {"request_id": str(uuid4()), "priority": 10}])
def test_invalid_jobs_never_write(api_client, extra):
    target = experiment(api_client)
    assert api_client.post(f"/experiments/{target}/jobs", json=extra).status_code == 422
    assert api_client.get("/jobs").json() == []


def test_benchmark_acceptance_atomically_saves_full_schedule_without_execution(api_client, monkeypatch):
    monkeypatch.setattr("app.execution.make_driver", lambda *_: pytest.fail("No execution during acceptance"))
    body = {"request_id": str(uuid4()), "repetitions": 2}
    job = api_client.post("/benchmark-jobs", json=body).json()
    assert job["kind"] == "benchmark" and job["status"] == "queued"
    assert api_client.post("/benchmark-jobs", json=body).json() == job
    report = api_client.get(f'/benchmarks/{job["benchmark_id"]}').json()
    assert len(report["items"]) == 18
    assert report["summary"]["overall"]["planned"] == report["summary"]["overall"]["pending"] == 18
    assert all(item["run"] is None for item in report["items"])
    private_experiment = report["items"][0]["experiment_id"]
    assert api_client.post(f"/experiments/{private_experiment}/jobs", json={"mode": "demo", "request_id": str(uuid4())}).status_code == 409


@pytest.fixture
def durable(test_engine):
    """Committed fixtures for real competing connections; remove only our own history."""
    jobs, experiments = set(), set()
    def submit(*, benchmark=False, mode="demo", request_id=None):
        with Session(test_engine, expire_on_commit=False) as session:
            if benchmark:
                job = enqueue_benchmark(BenchmarkJobRequest(request_id=request_id or uuid4()), session)
            else:
                with session.begin():
                    record = Experiment(name="Worker integration", agent_version="refund-v1", scenarios=["normal"])
                    session.add(record)
                    session.flush()
                    target = record.id
                    experiments.add(target)
                job = enqueue_run(target, RunJobRequest(request_id=request_id or uuid4(), mode=mode), session)
            jobs.add(job.id)
            return job.id
    yield SimpleNamespace(submit=submit, engine=test_engine)
    with test_engine.begin() as connection:
        benchmark_ids = list(connection.scalars(select(Job.benchmark_id).where(Job.id.in_(jobs), Job.benchmark_id.is_not(None))))
        experiments.update(connection.scalars(select(BenchmarkItem.experiment_id).where(BenchmarkItem.benchmark_id.in_(benchmark_ids))))
        connection.execute(delete(Job).where(Job.id.in_(jobs)))
        connection.execute(delete(BenchmarkItem).where(BenchmarkItem.benchmark_id.in_(benchmark_ids)))
        connection.execute(delete(AgentRun).where(AgentRun.experiment_id.in_(experiments)))
        connection.execute(delete(Experiment).where(Experiment.id.in_(experiments)))
        connection.execute(delete(Benchmark).where(Benchmark.id.in_(benchmark_ids)))


def expire(engine, job_id):
    with engine.begin() as connection:
        connection.execute(text("UPDATE jobs SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=:id"), {"id": job_id})


def test_competing_claims_get_one_owner_and_terminal_key_never_reexecutes(durable):
    target = durable.submit()
    barrier = Barrier(2)
    def claim(name):
        with Session(durable.engine, expire_on_commit=False) as session:
            barrier.wait(timeout=5)
            return claim_next(session, name)
    with ThreadPoolExecutor(max_workers=2) as pool:
        leases = list(pool.map(claim, ["first", "second"]))
    assert sum(lease is not None for lease in leases) == 1
    lease = next(lease for lease in leases if lease)
    assert lease.job_id == target
    with Session(durable.engine, expire_on_commit=False) as session:
        assert process_claimed(session, lease) == "succeeded"
        with pytest.raises(LeaseLost):
            process_claimed(session, lease)
        session.rollback()
        assert claim_next(session, "third") is None
        job = session.get(Job, target)
        run = session.get(AgentRun, job.run_id)
        assert job.status == "succeeded" and job.attempts == 1 and run.status == "completed"
        assert run.evaluation["verdict"] == run.grounding_evaluation["verdict"] == "passed"
        assert session.scalar(select(func.count()).select_from(AgentRun).where(AgentRun.experiment_id == job.experiment_id)) == 1


def test_skip_locked_does_not_block_another_queued_job(durable):
    first, second = durable.submit(), durable.submit()
    with Session(durable.engine) as owner, owner.begin():
        owner.scalar(select(Job).where(Job.id == first).with_for_update())
        with Session(durable.engine, expire_on_commit=False) as other:
            lease = claim_next(other, "other-worker")
            assert lease.job_id == second


def test_heartbeat_and_model_calls_hold_no_application_transaction(durable, monkeypatch):
    target = durable.submit()
    with Session(durable.engine, expire_on_commit=False) as session:
        lease = claim_next(session, "heartbeat-worker")
        calls = []
        class Observed(DemoDriver):
            def decide(self, history):
                assert not session.in_transaction()
                with Session(durable.engine, expire_on_commit=False) as pulse:
                    heartbeat(pulse, lease, 30)
                calls.append(1)
                return super().decide(history)
        monkeypatch.setattr("app.execution.make_driver", lambda _: (Observed(), None))
        assert process_claimed(session, lease) == "succeeded" and len(calls) == 3
        assert session.get(Job, target).lease_token is None


def test_expiry_before_run_creation_can_requeue_but_old_token_cannot_renew_or_publish(durable):
    target = durable.submit()
    with Session(durable.engine, expire_on_commit=False) as session:
        old = claim_next(session, "dead-worker")
        expire(durable.engine, target)
        with pytest.raises(LeaseLost):
            heartbeat(session, old, 30)
        assert recover_expired(session) == 1
        new = claim_next(session, "replacement")
        assert new.token != old.token
        with pytest.raises(LeaseLost):
            finish_job(session, old)
        assert process_claimed(session, new) == "succeeded"
        assert session.get(Job, target).attempts == 2


def test_expiry_after_business_action_marks_unknown_instead_of_replaying(durable, monkeypatch):
    target = durable.submit()
    with Session(durable.engine, expire_on_commit=False) as session:
        lease = claim_next(session, "stale-worker")
        class ExpiredAfterRefund(DemoDriver):
            def decide(self, history):
                turn = super().decide(history)
                if turn.answer:
                    expire(durable.engine, target)
                return turn
        monkeypatch.setattr("app.execution.make_driver", lambda _: (ExpiredAfterRefund(), None))
        assert process_claimed(session, lease) == "lost"
        assert recover_expired(session) == 1
        assert claim_next(session, "replacement") is None
        job = session.get(Job, target)
        run = session.get(AgentRun, job.run_id)
        assert job.status == run.status == "interrupted" and job.attempts == 1
        assert run.evaluation is None and run.grounding_evaluation is None
        assert "unknown" in run.error and run.output is None


def test_late_exception_recovers_saved_result_without_replay(durable, monkeypatch):
    from app.execution import start_run
    target = durable.submit()
    def late(*args, **kwargs):
        start_run(*args, **kwargs)
        raise RuntimeError("private-cleanup-message")
    monkeypatch.setattr("app.worker.start_run", late)
    with Session(durable.engine, expire_on_commit=False) as session:
        lease = claim_next(session, "late-worker")
        assert process_claimed(session, lease) == "succeeded"
        job = session.get(Job, target)
        assert job.status == "succeeded" and job.error is None


@pytest.mark.parametrize("benchmark", [False, True])
def test_changed_execution_fingerprint_fails_closed_before_any_agent(durable, monkeypatch, benchmark):
    target = durable.submit(benchmark=benchmark)
    monkeypatch.setattr("app.worker.execution_fingerprint", lambda: "different")
    monkeypatch.setattr("app.execution.make_driver", lambda *_: pytest.fail("Do not execute changed work"))
    with Session(durable.engine, expire_on_commit=False) as session:
        lease = claim_next(session, "different-worker")
        assert process_claimed(session, lease) == "failed"
        job = session.get(Job, target)
        assert job.status == "failed" and "differ" in job.error
        if benchmark:
            report = read_benchmark(job.benchmark_id, session)
            assert report.summary.overall.infrastructure_failed == report.summary.overall.planned == 9
            assert report.status == "failed"


def test_benchmark_resumes_unstarted_cells_and_recovers_saved_result(durable, monkeypatch):
    from app.execution import start_run
    target = durable.submit(benchmark=True)
    class Crash(BaseException):
        pass
    def crash_after_save(*args, **kwargs):
        start_run(*args, **kwargs)
        raise Crash()
    with Session(durable.engine, expire_on_commit=False) as session:
        lease = claim_next(session, "crashed-benchmark-worker")
        monkeypatch.setattr("app.benchmark.start_run", crash_after_save)
        with pytest.raises(Crash):
            process_claimed(session, lease)
        session.rollback()
        expire(durable.engine, target)
        assert recover_expired(session) == 1
        recovered = claim_next(session, "new-benchmark-worker")
        called = []
        def remaining(*args, **kwargs):
            called.append(kwargs["run_id"])
            return start_run(*args, **kwargs)
        monkeypatch.setattr("app.benchmark.start_run", remaining)
        assert process_claimed(session, recovered) == "succeeded"
        job = session.get(Job, target)
        report = read_benchmark(job.benchmark_id, session)
        assert len(called) == 8 and report.items[0].run_id not in called
        assert report.status == "completed" and report.summary.overall.recorded == 9
        assert report.summary.overall.execution_completed == 7
        assert job.attempts == 2


def test_started_unknown_benchmark_cell_is_retained_and_never_replayed(durable):
    from app.agent import TASK
    from app.tools import RefundSandbox
    target = durable.submit(benchmark=True)
    with Session(durable.engine, expire_on_commit=False) as session:
        lease = claim_next(session, "interrupted-cell-worker")
        with session.begin():
            job = lease.check(session)
            item = session.scalar(select(BenchmarkItem).where(BenchmarkItem.benchmark_id == job.benchmark_id).order_by(BenchmarkItem.position))
            item.status = "running"
            state = RefundSandbox().snapshot()
            session.add(AgentRun(id=item.id, experiment_id=item.experiment_id, status="running", mode=item.mode,
                                 task=TASK, initial_state=state, final_state=state))
            interrupted_id = item.id
        expire(durable.engine, target)
        recover_expired(session)
        lease = claim_next(session, "continuing-worker")
        assert process_claimed(session, lease) == "succeeded"
        report = read_benchmark(session.get(Job, target).benchmark_id, session)
        assert report.status == "failed"
        assert report.summary.overall.recorded == 8 and report.summary.overall.infrastructure_failed == 1
        assert report.summary.overall.planned == 9 and report.summary.overall.pending == 0
        assert report.items[0].run_id == interrupted_id and report.items[0].run.status == "interrupted"


@pytest.mark.parametrize("benchmark", [False, True])
def test_recovery_is_bounded_and_does_not_hide_unexecuted_work(durable, benchmark):
    target = durable.submit(benchmark=benchmark)
    with Session(durable.engine, expire_on_commit=False) as session:
        claim_next(session, "last-worker")
        with session.begin():
            session.get(Job, target).attempts = 3
        expire(durable.engine, target)
        recover_expired(session)
        assert claim_next(session, "never-worker") is None
        job = session.get(Job, target)
        assert job.status == "interrupted"
        if benchmark:
            report = read_benchmark(job.benchmark_id, session)
            assert report.summary.overall.infrastructure_failed == report.summary.overall.planned == 9


def test_migration_refuses_to_discard_job_receipts(api_client, database_connection):
    target = experiment(api_client)
    job = api_client.post(f"/experiments/{target}/jobs", json={"mode": "demo", "request_id": str(uuid4())}).json()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["connection"] = database_connection
    with pytest.raises(IntegrityError), database_connection.begin_nested():
        command.downgrade(config, "7ba56d892c41")
    assert api_client.get(f'/jobs/{job["id"]}').json() == job


def test_worker_cannot_report_success_without_a_terminal_artifact(durable, monkeypatch):
    target = durable.submit()
    monkeypatch.setattr("app.worker.start_run", lambda *args, **kwargs: None)
    with Session(durable.engine, expire_on_commit=False) as session:
        lease = claim_next(session, "empty-worker")
        assert process_claimed(session, lease) == "failed"
        assert session.get(Job, target).status == "failed"


def test_processing_success_is_separate_from_agent_correctness(durable):
    target = durable.submit(mode="demo_claim_only")
    with Session(durable.engine, expire_on_commit=False) as session:
        lease = claim_next(session, "negative-control-worker")
        assert process_claimed(session, lease) == "succeeded"
        job = session.get(Job, target)
        run = session.get(AgentRun, job.run_id)
        assert run.evaluation["verdict"] == run.grounding_evaluation["verdict"] == "failed"


def test_provider_preflight_failure_keeps_a_safe_job_error_without_run(durable, monkeypatch):
    from app.providers import ProviderNotConfigured
    target = durable.submit()
    def unavailable(_):
        raise ProviderNotConfigured("private-provider-payload")
    monkeypatch.setattr("app.execution.make_driver", unavailable)
    with Session(durable.engine, expire_on_commit=False) as session:
        lease = claim_next(session, "unconfigured-worker")
        assert process_claimed(session, lease) == "failed"
        job = session.get(Job, target)
        assert session.get(AgentRun, job.run_id) is None
        assert "private-provider-payload" not in job.error


def test_old_worker_detects_disk_changes_before_claiming_new_work(durable):
    from app.worker import WorkerCodeChanged, work_once
    target = durable.submit()
    with pytest.raises(WorkerCodeChanged):
        work_once(durable.engine, "outdated-worker", worker_fingerprint="old-imported-code")
    with Session(durable.engine) as session:
        assert session.get(Job, target).status == "queued"


def test_item_exception_marks_started_run_interrupted_before_suite_finishes(durable, monkeypatch):
    from app.agent import TASK
    from app.execution import start_run
    from app.tools import RefundSandbox
    target = durable.submit(benchmark=True)
    calls = []
    def fail_first(experiment_id, mode, session, **kwargs):
        calls.append(kwargs["run_id"])
        if len(calls) > 1:
            return start_run(experiment_id, mode, session, **kwargs)
        with session.begin():
            kwargs["lease"].check(session)
            state = RefundSandbox().snapshot()
            session.add(AgentRun(id=kwargs["run_id"], experiment_id=experiment_id, mode=mode, status="running",
                                 task=TASK, initial_state=state, final_state=state))
        raise RuntimeError("failed before saving terminal result")
    monkeypatch.setattr("app.benchmark.start_run", fail_first)
    with Session(durable.engine, expire_on_commit=False) as session:
        lease = claim_next(session, "partial-suite-worker")
        assert process_claimed(session, lease) == "succeeded"
        report = read_benchmark(session.get(Job, target).benchmark_id, session)
        assert report.summary.overall.recorded == 8 and report.summary.overall.infrastructure_failed == 1
        assert report.items[0].run.status == "interrupted"


def test_real_worker_thread_renews_lease_while_model_is_blocked(durable, monkeypatch):
    from app.jobs import heartbeat as renew
    from app.worker import work_once
    target = durable.submit()
    entered, renewed, release = Event(), Event(), Event()
    class Blocked(DemoDriver):
        def decide(self, history):
            if not entered.is_set():
                entered.set()
                assert release.wait(10)
            return super().decide(history)
    def pulse(*args):
        renew(*args)
        renewed.set()
    monkeypatch.setattr("app.execution.make_driver", lambda _: (Blocked(), None))
    monkeypatch.setattr("app.worker.heartbeat", pulse)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(work_once, durable.engine, "live-heartbeat-worker", 15)
        try:
            assert entered.wait(5)
            with Session(durable.engine) as observer:
                before = observer.get(Job, target).lease_expires_at
            assert renewed.wait(7)
            with Session(durable.engine) as observer:
                assert observer.get(Job, target).lease_expires_at > before
        finally:
            release.set()
        assert future.result(timeout=5) == "succeeded"
