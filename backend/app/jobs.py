"""PostgreSQL queue admission, ownership, and conservative crash recovery."""

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.job_schemas import BenchmarkJobRequest, RunJobRequest
from app.models import AgentRun, Benchmark, BenchmarkItem, Experiment, Job

ACTIVE = ("queued", "running")
TERMINAL_RUN = ("completed", "failed")
MAX_CLAIMS = 3
QUEUE_CAPACITY = 100
ADMISSION_LOCK = 742619083


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def execution_fingerprint() -> str:
    backend = Path(__file__).resolve().parents[1]
    paths = sorted((backend / "app").glob("*.py")) + [backend / "uv.lock", backend / "pyproject.toml"]
    return digest({"files": {str(path.relative_to(backend)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
                   "settings": {name: os.environ.get(name) for name in ("OLLAMA_MODEL", "OLLAMA_BASE_URL", "OPENAI_MODEL")}})


class LeaseLost(Exception):
    """The caller is no longer allowed to execute or publish job evidence."""


@dataclass(frozen=True)
class Lease:
    job_id: UUID
    token: UUID

    def check(self, session: Session) -> Job:
        job = session.scalar(select(Job).where(
            Job.id == self.job_id, Job.status == "running", Job.lease_token == self.token
        ).with_for_update().execution_options(populate_existing=True))
        now = session.scalar(select(func.clock_timestamp()))
        if job is None or job.lease_expires_at <= now:
            raise LeaseLost("Worker ownership expired; no further result may be published.")
        return job


def reservation(session: Session, experiment_id: UUID) -> Job | None:
    return session.scalar(select(Job).where(Job.status.in_(ACTIVE), (
        (Job.experiment_id == experiment_id) |
        Job.benchmark_id.in_(select(BenchmarkItem.benchmark_id).where(BenchmarkItem.experiment_id == experiment_id)))))


def _existing(session: Session, request_id: UUID, request_hash: str) -> Job | None:
    job = session.scalar(select(Job).where(Job.request_id == request_id))
    if job and job.request_hash != request_hash:
        raise HTTPException(409, "This request ID was already used for different work.")
    return job


def _admit(session: Session, request_id: UUID, request_hash: str) -> Job | None:
    session.scalar(select(func.pg_advisory_xact_lock(ADMISSION_LOCK)))
    existing = _existing(session, request_id, request_hash)
    if existing:
        return existing
    if session.scalar(select(func.count()).select_from(Job).where(Job.status.in_(ACTIVE))) >= QUEUE_CAPACITY:
        raise HTTPException(429, "The job queue is full. Check existing work and try again later.")
    return None


def enqueue_run(experiment_id: UUID, request: RunJobRequest, session: Session) -> Job:
    request_hash = digest({"kind": "run", "experiment_id": str(experiment_id), "mode": request.mode})
    fingerprint = execution_fingerprint()
    with session.begin():
        existing = _admit(session, request.request_id, request_hash)
        if existing:
            return existing
        experiment = session.scalar(select(Experiment).where(Experiment.id == experiment_id).with_for_update())
        if experiment is None:
            raise HTTPException(404, "Experiment not found")
        if (experiment.agent_version != "refund-v1" or len(experiment.scenarios) != 1
                or experiment.scenarios[0] not in {"normal", "timeout_after_commit", "permission_denied"}):
            raise HTTPException(409, "Choose refund-v1 with exactly one supported scenario.")
        if experiment.status == "running" or reservation(session, experiment_id):
            raise HTTPException(409, "This experiment already has queued or running work.")
        job = Job(request_id=request.request_id, request_hash=request_hash, kind="run", status="queued",
                  execution_fingerprint=fingerprint, experiment_id=experiment_id, run_id=uuid4(),
                  payload={"mode": request.mode, "scenario": experiment.scenarios[0], "agent_version": experiment.agent_version})
        session.add(job)
        session.flush()
        session.refresh(job)
    return job


def enqueue_benchmark(request: BenchmarkJobRequest, session: Session) -> Job:
    from app.benchmark import prepare_benchmark
    from app.benchmark_schemas import BenchmarkRequest
    configuration = request.model_dump(exclude={"request_id"})
    request_hash = digest({"kind": "benchmark", **configuration})
    fingerprint = execution_fingerprint()
    with session.begin():
        existing = _admit(session, request.request_id, request_hash)
        if existing:
            return existing
        benchmark_id = prepare_benchmark(BenchmarkRequest(**configuration), session)
        job = Job(request_id=request.request_id, request_hash=request_hash, kind="benchmark", status="queued",
                  execution_fingerprint=fingerprint, benchmark_id=benchmark_id, payload=configuration)
        session.add(job)
        session.flush()
        session.refresh(job)
    return job


def _finish(job: Job, status: str, error: str | None = None):
    job.status, job.error = status, error
    job.finished_at = func.clock_timestamp()
    job.lease_token = job.lease_expires_at = None


def interrupt_run(run: AgentRun, session: Session):
    if run.status == "running":
        run.status = "interrupted"
        run.error = "Execution was interrupted before terminal evidence was saved. Final state and fault outcome are unknown; no automatic replay was made."
        run.finished_at = func.clock_timestamp()
        session.execute(update(Experiment).where(Experiment.id == run.experiment_id).values(status="failed"))


def reconcile_benchmark(benchmark: Benchmark, session: Session, *, abandon=False) -> bool:
    from app.benchmark import update_summary
    for item in session.scalars(select(BenchmarkItem).where(BenchmarkItem.benchmark_id == benchmark.id).order_by(BenchmarkItem.position)):
        if item.status not in {"pending", "running"}:
            continue
        run = session.get(AgentRun, item.id)
        if run:
            interrupt_run(run, session)
            item.run_id = run.id
            item.status = "completed" if run.status in TERMINAL_RUN else "failed"
            item.error = None if item.status == "completed" else "Worker interruption left no terminal execution evidence. This cell will not be replayed."
        elif abandon:
            item.status, item.error = "failed", "Collection stopped before this cell executed."
        else:
            item.status, item.error = "pending", None
    update_summary(benchmark, session)
    done = benchmark.summary["overall"]["pending"] == 0
    if done:
        benchmark.status = "failed" if benchmark.summary["overall"]["infrastructure_failed"] else "completed"
        benchmark.finished_at = func.clock_timestamp()
    return done


def recover_expired(session: Session) -> int:
    recovered = 0
    with session.begin():
        expired = list(session.scalars(select(Job).where(Job.status == "running", Job.lease_expires_at <= func.clock_timestamp())
                                      .order_by(Job.created_at, Job.id).limit(100).with_for_update(skip_locked=True)))
        for job in expired:
            recovered += 1
            if job.kind == "run":
                run = session.get(AgentRun, job.run_id)
                if run:
                    interrupt_run(run, session)
                    _finish(job, "succeeded" if run.status in TERMINAL_RUN else "interrupted",
                            None if run.status in TERMINAL_RUN else run.error)
                    continue
            else:
                benchmark = session.get(Benchmark, job.benchmark_id)
                if reconcile_benchmark(benchmark, session):
                    _finish(job, "succeeded")
                    continue
                if job.attempts >= MAX_CLAIMS:
                    reconcile_benchmark(benchmark, session, abandon=True)
                    _finish(job, "interrupted", "Worker recovery limit reached. Saved cells retained.")
                    continue
            if job.attempts >= MAX_CLAIMS:
                _finish(job, "interrupted", "Worker recovery limit reached before execution started.")
            else:
                job.status, job.lease_token, job.lease_expires_at = "queued", None, None
                job.error = "Previous worker lease expired. Only work that never started may continue."
    return recovered


def claim_next(session: Session, worker_id: str, lease_seconds: int = 30) -> Lease | None:
    if not 15 <= lease_seconds <= 600 or not worker_id or len(worker_id) > 100:
        raise ValueError("Invalid worker lease configuration")
    with session.begin():
        job = session.scalar(select(Job).where(Job.status == "queued").order_by(Job.created_at, Job.id)
                             .limit(1).with_for_update(skip_locked=True))
        if job is None:
            return None
        token = uuid4()
        job.status, job.lease_token, job.worker_id = "running", token, worker_id
        job.lease_expires_at = func.clock_timestamp() + timedelta(seconds=lease_seconds)
        job.started_at = job.started_at if job.started_at is not None else func.clock_timestamp()
        job.attempts += 1
        job.error = None
        lease = Lease(job.id, token)
    return lease


def heartbeat(session: Session, lease: Lease, lease_seconds: int) -> None:
    with session.begin():
        job = lease.check(session)
        job.lease_expires_at = func.clock_timestamp() + timedelta(seconds=lease_seconds)


def finish_job(session: Session, lease: Lease, *, failure: str | None = None) -> str:
    with session.begin():
        job = lease.check(session)
        if failure is None:
            artifact = session.get(AgentRun, job.run_id) if job.kind == "run" else session.get(Benchmark, job.benchmark_id)
            terminal = artifact is not None and artifact.status in TERMINAL_RUN
            if job.kind == "benchmark":
                terminal = terminal and artifact.finished_at is not None and artifact.summary["overall"]["pending"] == 0
            if not terminal:
                failure = "Worker returned without a terminal result. Saved evidence retained; no execution was replayed."
        if failure:
            if job.kind == "run":
                run = session.get(AgentRun, job.run_id)
                if run and run.status in TERMINAL_RUN:
                    _finish(job, "succeeded")
                    return "succeeded"
                if run:
                    interrupt_run(run, session)
                    _finish(job, "interrupted", run.error)
                    return "interrupted"
            else:
                reconcile_benchmark(session.get(Benchmark, job.benchmark_id), session, abandon=True)
            _finish(job, "failed", failure)
        else:
            _finish(job, "succeeded")
        return job.status
