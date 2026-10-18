"""Bounded synchronous benchmark execution using the existing single-run path."""

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.benchmark_schemas import (BenchmarkCounts, BenchmarkDetail, BenchmarkItemRead,
                                   BenchmarkRequest, BenchmarkSummary, DriverSummary)
from app.benchmark_suite import MODES, build_manifest
from app.execution import start_run
from app.models import AgentRun, Benchmark, BenchmarkItem, Experiment
from app.jobs import Lease, LeaseLost, interrupt_run, reservation
from app.schemas import RunRead

logger = logging.getLogger(__name__)


def summarize(manifest: dict, rows: list[tuple[BenchmarkItem, AgentRun | None]]) -> BenchmarkSummary:
    """Use planned denominators. Missing or unevaluable results never become passes."""
    overall = BenchmarkCounts()
    drivers = {mode: BenchmarkCounts() for mode in MODES}
    by_position = {item.position: (item, run) for item, run in rows}
    for cell in manifest["schedule"]:
        pair = by_position.get(cell["position"])
        for counts in (overall, drivers[cell["mode"]]):
            counts.planned += 1
            counts.fault_selected += cell["scenario"] != "normal"
            if pair is None:
                counts.infrastructure_failed += 1
                continue
            item, run = pair
            if item.status in {"pending", "running"}:
                counts.pending += 1
                continue
            if item.status == "failed":
                counts.infrastructure_failed += 1
                continue
            if run is None or run.status not in {"completed", "failed"}:
                raise ValueError("Completed benchmark item has no terminal execution")
            counts.recorded += 1
            counts.execution_completed += run.status == "completed"
            counts.execution_failed += run.status == "failed"
            counts.fault_injected += run.fault_injected
            ledger = run.evaluation or {}
            recovery = run.recovery_evaluation or {}
            counts.ledger_passed += ledger.get("verdict") == "passed"
            counts.ledger_failed += ledger.get("verdict") == "failed"
            counts.ledger_not_evaluable += ledger.get("verdict") not in {"passed", "failed"}
            counts.recovery_passed += recovery.get("verdict") == "passed"
            counts.recovery_failed += recovery.get("verdict") == "failed"
            counts.recovery_not_applicable += recovery.get("verdict") == "not_applicable"
            counts.recovery_not_evaluable += recovery.get("verdict") not in {"passed", "failed", "not_applicable"}
    return BenchmarkSummary(overall=overall, drivers=[DriverSummary(mode=mode, counts=drivers[mode]) for mode in MODES])


def item_rows(benchmark_id: UUID, session: Session):
    return list(session.execute(
        select(BenchmarkItem, AgentRun)
        .outerjoin(AgentRun, BenchmarkItem.run_id == AgentRun.id)
        .where(BenchmarkItem.benchmark_id == benchmark_id)
        .order_by(BenchmarkItem.position)
    ))


def update_summary(benchmark: Benchmark, session: Session) -> None:
    session.flush()
    benchmark.summary = summarize(benchmark.manifest, item_rows(benchmark.id, session)).model_dump(mode="json")


def prepare_benchmark(request: BenchmarkRequest, session: Session) -> UUID:
    """Caller commits this complete schedule atomically with its job receipt."""
    revision = session.scalar(text("SELECT version_num FROM alembic_version"))
    manifest = build_manifest(request.repetitions, revision)
    benchmark = Benchmark(suite_version=request.suite_version, status="running", manifest=manifest,
                          summary=BenchmarkSummary(overall=BenchmarkCounts(), drivers=[]).model_dump(mode="json"))
    session.add(benchmark)
    session.flush()
    for cell in manifest["schedule"]:
        experiment = Experiment(name=f'Benchmark {cell["case_key"]}', agent_version="refund-v1", scenarios=[cell["scenario"]])
        session.add(experiment)
        session.flush()
        session.add(BenchmarkItem(benchmark_id=benchmark.id, experiment_id=experiment.id,
                                 position=cell["position"], case_key=cell["case_key"], mode=cell["mode"],
                                 repetition=cell["repetition"], status="pending"))
    update_summary(benchmark, session)
    return benchmark.id


def run_benchmark(request: BenchmarkRequest, session: Session) -> UUID:
    # Inline CLI/testing entry point shares exactly the same scheduled execution path.
    with session.begin():
        benchmark_id = prepare_benchmark(request, session)
    execute_benchmark(benchmark_id, session)
    return benchmark_id


def execute_benchmark(benchmark_id: UUID, session: Session, *, lease: Lease | None = None) -> None:
    with session.begin():
        if lease and lease.check(session).benchmark_id != benchmark_id:
            raise ValueError("Job target does not match benchmark")
        schedule = list(session.execute(select(BenchmarkItem.id, BenchmarkItem.experiment_id, BenchmarkItem.mode)
                                        .where(BenchmarkItem.benchmark_id == benchmark_id).order_by(BenchmarkItem.position)))
    for item_id, experiment_id, mode in schedule:
        with session.begin():
            if lease:
                lease.check(session)
            elif reservation(session, experiment_id):
                raise HTTPException(409, "This benchmark is reserved by a durable job.")
            item = session.get(BenchmarkItem, item_id)
            if item.status in {"completed", "failed"}:
                continue
            if item.status != "pending":
                raise ValueError("Interrupted cells require recovery before continuation")
            item.status = "running"
        execution_error = False
        try:
            arguments = {"run_id": item_id}
            if lease:
                arguments["lease"] = lease
            start_run(experiment_id, mode, session, **arguments)
        except LeaseLost:
            session.rollback()
            raise
        except Exception as exc:
            session.rollback()
            execution_error = True
            logger.error("Benchmark item execution interrupted: %s", type(exc).__name__)
        with session.begin():
            if lease:
                lease.check(session)
            item = session.get(BenchmarkItem, item_id)
            saved = session.get(AgentRun, item_id)
            if lease and saved is not None and saved.status == "running":
                interrupt_run(saved, session)
            item.run_id = saved.id if saved else None
            if saved is not None and saved.status in {"completed", "failed"}:
                item.status = "completed"
                if execution_error:
                    item.error = "Execution reported an interruption after saving its result. Saved evidence retained."
            else:
                item.status = "failed"
                item.error = "Execution infrastructure did not produce a terminal result. No automatic retry was made."
            update_summary(session.get(Benchmark, benchmark_id), session)
    with session.begin():
        if lease:
            lease.check(session)
        benchmark = session.get(Benchmark, benchmark_id)
        benchmark.status = "failed" if benchmark.summary["overall"]["infrastructure_failed"] else "completed"
        benchmark.finished_at = datetime.now(timezone.utc)


def read_benchmark(benchmark_id: UUID, session: Session) -> BenchmarkDetail:
    benchmark = session.get(Benchmark, benchmark_id)
    if benchmark is None:
        raise HTTPException(404, "Benchmark not found")
    items = []
    for item, run in item_rows(benchmark_id, session):
        items.append(BenchmarkItemRead(
            id=item.id, experiment_id=item.experiment_id, run_id=item.run_id, position=item.position,
            case_key=item.case_key, mode=item.mode, repetition=item.repetition, status=item.status,
            error=item.error, run=RunRead.model_validate(run) if run else None,
        ))
    return BenchmarkDetail(
        id=benchmark.id, suite_version=benchmark.suite_version, status=benchmark.status,
        summary=benchmark.summary, started_at=benchmark.started_at, finished_at=benchmark.finished_at,
        manifest=benchmark.manifest, items=items,
    )


if __name__ == "__main__":
    import argparse
    import json

    from pydantic import ValidationError

    from app.database import engine
    from app.telemetry import configure_tracing, shutdown_tracing

    parser = argparse.ArgumentParser(description="Run the fixed scripted refund resilience benchmark.")
    parser.add_argument("--repetitions", type=int, default=1, help="1–3 repetitions per cell; scripts only")
    args = parser.parse_args()
    try:
        request = BenchmarkRequest(repetitions=args.repetitions)
    except ValidationError:
        parser.error("Repetitions must be between 1 and 3.")
    provider = configure_tracing()
    try:
        with Session(engine, expire_on_commit=False) as session:
            benchmark_id = run_benchmark(request, session)
            result = read_benchmark(benchmark_id, session)
            print(json.dumps({"benchmark_id": str(benchmark_id), "status": result.status,
                              "summary": result.summary.model_dump(mode="json")}, indent=2))
    finally:
        shutdown_tracing(provider)
    raise SystemExit(0 if result.status == "completed" else 1)
