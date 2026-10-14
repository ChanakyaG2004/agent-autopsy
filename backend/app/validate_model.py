"""Explicit, bounded live validation. Default invocation only checks configuration."""

import argparse
import json
import os

from sqlalchemy.orm import Session

from app.database import engine
from app.execution import start_run
from app.models import Experiment
from app.schemas import RunRead
from app.telemetry import configure_tracing, shutdown_tracing


def configuration_status() -> dict:
    return {"key_configured": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
            "model_configured": bool(os.environ.get("OPENAI_MODEL", "").strip())}


def validation_report(run: RunRead) -> dict:
    measured = run.model_telemetry
    checks = {
        "execution_completed": run.status == "completed",
        "provider_responses_completed": bool(measured and measured.requests) and all(
            request.outcome == "response" and request.response_status == "completed"
            for request in measured.requests),
        "reported_model_available": bool(measured and measured.requests) and all(
            request.reported_model is not None for request in measured.requests),
        "usage_available_for_every_attempt": bool(measured and measured.usage_complete),
        "ledger_matches_scenario": run.evaluation is not None and run.evaluation.verdict == (
            "failed" if run.scenario == "permission_denied" else "passed"),
        "recovery_matches_scenario": run.recovery_evaluation is not None and run.recovery_evaluation.verdict == (
            "not_applicable" if run.scenario == "normal" else "passed"),
        "selected_fault_exercised": run.scenario == "normal" or run.fault_injected,
    }
    return {
        "validation_version": "model-validation-v1", "passed": all(checks.values()), "checks": checks,
        "experiment_id": str(run.experiment_id), "run_id": str(run.id), "trace_id": run.trace_id,
        "scenario": run.scenario, "execution_status": run.status,
        "ledger_verdict": run.evaluation.verdict if run.evaluation else None,
        "recovery_verdict": run.recovery_evaluation.verdict if run.recovery_evaluation else None,
        "model_telemetry": measured.model_dump(mode="json") if measured else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check backend model configuration, or explicitly execute one validation run.")
    parser.add_argument("--execute", action="store_true", help="Make potentially billable model requests and persist a validation run")
    parser.add_argument("--scenario", choices=["normal", "timeout_after_commit", "permission_denied"], default="normal")
    args = parser.parse_args(argv)
    configured = configuration_status()
    ready = all(configured.values())
    if not args.execute or not ready:
        print(json.dumps({"configuration": configured, "ready": ready, "executed": False,
                          "message": "Use --execute for one model-backed run." if ready else
                          "Set OPENAI_API_KEY and OPENAI_MODEL in the backend environment. No request was made."}, indent=2))
        return 0 if ready else 2
    provider = configure_tracing()
    try:
        with Session(engine, expire_on_commit=False) as session:
            with session.begin():
                experiment = Experiment(name=f"Model validation {args.scenario}", agent_version="refund-v1", scenarios=[args.scenario])
                session.add(experiment)
                session.flush()
                experiment_id = experiment.id
            run = RunRead.model_validate(start_run(experiment_id, "openai", session))
            report = validation_report(run)
            print(json.dumps(report, indent=2))
            return 0 if report["passed"] else 1
    finally:
        shutdown_tracing(provider)


if __name__ == "__main__":
    raise SystemExit(main())
