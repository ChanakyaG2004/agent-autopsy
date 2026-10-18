"""Separate worker process. No model or suite execution occurs in queue HTTP handlers."""

import argparse
import logging
import signal
import socket
from threading import Event, Thread
from uuid import uuid4

from sqlalchemy.orm import Session

from app.benchmark import execute_benchmark
from app.database import engine
from app.execution import start_run
from app.jobs import Lease, LeaseLost, claim_next, execution_fingerprint, finish_job, heartbeat, recover_expired
from app.telemetry import configure_tracing, shutdown_tracing, span

logger = logging.getLogger(__name__)


class WorkerCodeChanged(Exception):
    """Restart is required; imported code cannot follow edits made on disk."""


def process_claimed(session: Session, lease: Lease, *, worker_fingerprint: str | None = None) -> str:
    with session.begin():
        job = lease.check(session)
        kind, payload, experiment_id, run_id, benchmark_id, fingerprint, attempt = (
            job.kind, dict(job.payload), job.experiment_id, job.run_id, job.benchmark_id, job.execution_fingerprint, job.attempts)
    current = execution_fingerprint()
    if fingerprint != (worker_fingerprint or current) or worker_fingerprint is not None and worker_fingerprint != current:
        return finish_job(session, lease, failure="Queued code or model settings differ from this worker. Review and submit a new job; no unstarted cell was executed.")
    try:
        with span("job.execute", "CHAIN", **{"job.id": str(lease.job_id), "job.kind": kind, "job.attempt": attempt}):
            if kind == "run":
                start_run(experiment_id, payload["mode"], session, run_id=run_id, lease=lease)
            else:
                execute_benchmark(benchmark_id, session, lease=lease)
    except LeaseLost:
        session.rollback()
        logger.warning("Job ownership lost; stale worker did not publish a terminal result.")
        return "lost"
    except Exception as exc:
        session.rollback()
        logger.error("Job processing failed: %s", type(exc).__name__)
        return finish_job(session, lease, failure="Worker could not complete this job. Check provider configuration and saved evidence before submitting new work.")
    return finish_job(session, lease)


def _keep_alive(database_engine, lease: Lease, lease_seconds: int, stop: Event):
    while not stop.wait(min(10, lease_seconds / 3)):
        try:
            with Session(database_engine, expire_on_commit=False) as session:
                heartbeat(session, lease, lease_seconds)
        except LeaseLost:
            return
        except Exception as exc:
            # Renewal may recover before expiry; it can never revive an already expired token.
            logger.error("Worker heartbeat unavailable: %s", type(exc).__name__)


def work_once(database_engine, worker_id: str, lease_seconds: int = 30, *, worker_fingerprint: str | None = None) -> str | None:
    current = execution_fingerprint()
    if worker_fingerprint is not None and worker_fingerprint != current:
        raise WorkerCodeChanged("Worker code or settings changed; restart the worker before accepting more jobs.")
    with Session(database_engine, expire_on_commit=False) as session:
        recover_expired(session)
        lease = claim_next(session, worker_id, lease_seconds)
        if lease is None:
            return None
        stop = Event()
        pulse = Thread(target=_keep_alive, args=(database_engine, lease, lease_seconds, stop), daemon=True)
        pulse.start()
        try:
            return process_claimed(session, lease, worker_fingerprint=worker_fingerprint or current)
        except LeaseLost:
            session.rollback()
            return "lost"
        finally:
            stop.set()
            pulse.join(timeout=5)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Process durable Agent Autopsy jobs using PostgreSQL leases.")
    parser.add_argument("--once", action="store_true", help="Recover expired ownership and process at most one queued job")
    parser.add_argument("--lease-seconds", type=int, default=30)
    parser.add_argument("--poll-seconds", type=float, default=1)
    args = parser.parse_args(argv)
    if not 15 <= args.lease_seconds <= 600 or not 0.2 <= args.poll_seconds <= 10:
        parser.error("Lease must be 15–600 seconds and polling 0.2–10 seconds.")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    worker_id = f"{socket.gethostname()[:60]}-{str(uuid4())[:8]}"
    stop = Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    startup_fingerprint = execution_fingerprint()
    provider = configure_tracing()
    logger.info("Worker %s ready", worker_id)
    try:
        while not stop.is_set():
            try:
                result = work_once(engine, worker_id, args.lease_seconds, worker_fingerprint=startup_fingerprint)
            except WorkerCodeChanged:
                logger.error("Worker code or settings changed. Restart required; no new job was claimed.")
                return 2
            except Exception as exc:
                logger.error("Queue unavailable: %s", type(exc).__name__)
                result = "failed"
            if args.once:
                return 1 if result in {"failed", "lost"} else 0
            if result is None or result in {"failed", "lost"}:
                stop.wait(args.poll_seconds)
    except KeyboardInterrupt:
        # In-flight ownership will expire and be recovered; never replay it here.
        pass
    finally:
        shutdown_tracing(provider)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
