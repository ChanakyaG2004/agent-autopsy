"""Short database transactions around synchronous execution, never around model calls."""

import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.agent import TASK, execute_agent
from app.evaluation import evaluate_refund, unavailable_evaluation
from app.recovery import evaluate_recovery, unavailable_recovery
from app.models import AgentRun, BenchmarkItem, Experiment
from app.jobs import Lease, reservation
from app.assurance import evaluate_security, evaluate_grounding, unavailable_security, unavailable_grounding
from app.model_telemetry import ModelTelemetry
from app.providers import ProviderNotConfigured, make_driver
from app.tools import RefundSandbox
from app.telemetry import mark_failure, set_json, span, trace_id

logger = logging.getLogger(__name__)


def start_run(experiment_id: UUID, mode: str, session: Session, *, run_id: UUID | None = None, lease: Lease | None = None) -> AgentRun:
    with session.begin():
        owner = lease.check(session) if lease else None
        experiment = session.scalar(select(Experiment).where(Experiment.id == experiment_id).with_for_update())
        if experiment is None:
            raise HTTPException(404, "Experiment not found")
        if (experiment.agent_version != "refund-v1" or len(experiment.scenarios) != 1
                or experiment.scenarios[0] not in {"normal", "timeout_after_commit", "permission_denied"}):
            raise HTTPException(409, "Execution supports refund-v1 with exactly one scenario: normal, timeout_after_commit, or permission_denied.")
        held = reservation(session, experiment_id)
        if held and (lease is None or held.id != lease.job_id):
            raise HTTPException(409, "This experiment is reserved by a durable job.")
        if owner:
            if owner.kind == "run":
                if (owner.experiment_id != experiment_id or owner.run_id != run_id or owner.payload["mode"] != mode
                        or owner.payload["scenario"] != experiment.scenarios[0] or owner.payload["agent_version"] != experiment.agent_version):
                    raise ValueError("Job target does not match its frozen request")
            elif session.scalar(select(BenchmarkItem.id).where(BenchmarkItem.id == run_id, BenchmarkItem.experiment_id == experiment_id,
                                                             BenchmarkItem.benchmark_id == owner.benchmark_id, BenchmarkItem.mode == mode)) is None:
                raise ValueError("Job target does not match its scheduled cell")
        scenario = experiment.scenarios[0]
        agent_version = experiment.agent_version
    try:
        driver, model_name = make_driver(mode)
    except ProviderNotConfigured as exc:
        raise HTTPException(503, str(exc)) from None
    if lease:
        driver = _LeasedDriver(driver, lease, session)
    try:
        with session.begin():
            if lease:
                lease.check(session)
            session.scalar(select(Experiment.id).where(Experiment.id == experiment_id).with_for_update())
            held = reservation(session, experiment_id)
            if held and (lease is None or held.id != lease.job_id):
                raise HTTPException(409, "This experiment is reserved by a durable job.")
            claimed = session.execute(
                update(Experiment)
                .where(Experiment.id == experiment_id, Experiment.status != "running")
                .values(status="running")
            ).rowcount
            if not claimed:
                raise HTTPException(409, "This experiment already has a running execution.")
            state = RefundSandbox().snapshot()
            run = AgentRun(id=run_id or uuid4(), experiment_id=experiment_id, mode=mode, scenario=scenario, model_name=model_name,
                           status="running", task=TASK, initial_state=state, final_state=state)
            session.add(run)
            session.flush()
            session.refresh(run)
            captured_run_id = str(run.id)
        with span("agent.run", "AGENT", **{
            "agent.run_id": captured_run_id, "agent.experiment_id": str(experiment_id),
            "agent.mode": mode, "agent.version": agent_version,
            "agent.scenario": scenario,
        }) as run_span:
            captured_trace_id = trace_id(run_span)
            if lease:
                run_span.set_attribute("job.id", str(lease.job_id))
                with session.begin():
                    lease.check(session)
                    run.trace_id = captured_trace_id
            set_json(run_span, "input", {"task": TASK})
            result = execute_agent(driver, scenario=scenario)
            try:
                candidate = getattr(driver, "model_telemetry", None)
                model_telemetry = candidate if mode in {"openai", "ollama"} and isinstance(candidate, ModelTelemetry) else None
            except Exception as exc:
                logger.error("Model telemetry unavailable: %s", type(exc).__name__)
                model_telemetry = None
            if model_telemetry is not None:
                run_span.set_attribute("agent.model_requests", model_telemetry.attempted_requests)
                run_span.set_attribute("agent.usage_complete", model_telemetry.usage_complete)
                run_span.set_attribute("agent.reported_usage_requests", model_telemetry.reported_usage_requests)
            run_span.set_attribute("agent.fault_injected", result.fault_injected)
            try:
                with span("evaluation.refund", "EVALUATOR", **{
                    "evaluation.version": "refund-ledger-v1",
                }) as evaluation_span:
                    evaluation = evaluate_refund(result.final_state)
                    set_json(evaluation_span, "output", {
                        "verdict": evaluation.verdict,
                        "checks": {check.name: check.passed for check in evaluation.checks},
                    })
            except Exception as exc:
                logger.error("Refund evaluation failed: %s", type(exc).__name__)
                evaluation = unavailable_evaluation()
            run_span.set_attribute("agent.evaluation.verdict", evaluation.verdict)
            run_span.set_attribute("agent.evaluation.version", evaluation.evaluator_version)
            try:
                with span("evaluation.recovery", "EVALUATOR", **{
                    "evaluation.version": "recovery-policy-v1",
                }) as recovery_span:
                    recovery = evaluate_recovery(
                        scenario=scenario, fault_injected=result.fault_injected,
                        steps=result.steps, initial_state=result.initial_state,
                        final_state=result.final_state,
                    )
                    set_json(recovery_span, "output", {
                        "verdict": recovery.verdict,
                        "checks": {check.name: check.passed for check in recovery.checks},
                    })
            except Exception as exc:
                logger.error("Recovery evaluation failed: %s", type(exc).__name__)
                recovery = unavailable_recovery()
            run_span.set_attribute("agent.recovery.verdict", recovery.verdict)
            run_span.set_attribute("agent.recovery.version", recovery.evaluator_version)
            assurance = {}
            for name, evaluate, fallback, arguments in [
                ("security", evaluate_security, unavailable_security,
                 dict(scenario=scenario, steps=result.steps, initial_state=result.initial_state, final_state=result.final_state)),
                ("grounding", evaluate_grounding, unavailable_grounding, dict(output=result.output, steps=result.steps)),
            ]:
                try:
                    with span(f"evaluation.{name}", "EVALUATOR") as assurance_span:
                        grade = evaluate(**arguments)
                        assurance_span.set_attribute("evaluation.version", grade.evaluator_version)
                        set_json(assurance_span, "output", {"verdict": grade.verdict,
                                 "checks": {check.name: check.passed for check in grade.checks}})
                except Exception as exc:
                    logger.error("%s evaluation failed: %s", name, type(exc).__name__)
                    grade = fallback()
                assurance[name] = grade
                run_span.set_attribute(f"agent.{name}.verdict", grade.verdict)
                run_span.set_attribute(f"agent.{name}.version", grade.evaluator_version)
            run_span.set_attribute("agent.execution_status", result.status)
            set_json(run_span, "output", {
                "execution_status": result.status,
                "refunded_cents": result.final_state["refunded_cents"],
                "refund_count": len(result.final_state["refunds"]),
            })
            if result.error:
                mark_failure(run_span, result.error)
            with session.begin():
                if lease:
                    lease.check(session)
                run.trace_id = captured_trace_id
                run.fault_injected = result.fault_injected
                run.evaluation = evaluation.model_dump(mode="json")
                run.recovery_evaluation = recovery.model_dump(mode="json")
                run.security_evaluation = assurance["security"].model_dump(mode="json")
                run.grounding_evaluation = assurance["grounding"].model_dump(mode="json")
                run.model_telemetry = model_telemetry.model_dump(mode="json") if model_telemetry else None
                run.status = result.status
                run.output = result.output
                run.error = result.error
                run.steps = result.steps
                run.final_state = result.final_state
                run.finished_at = datetime.now(timezone.utc)
                session.execute(update(Experiment).where(Experiment.id == experiment_id)
                                .values(status=result.status))
                session.flush()
                session.refresh(run)
        return run
    finally:
        close = getattr(driver, "close", None)
        if close:
            close()


class _LeasedDriver:
    def __init__(self, delegate, lease: Lease, session: Session):
        self.delegate, self.lease, self.session = delegate, lease, session

    def decide(self, history):
        with self.session.begin():
            self.lease.check(self.session)
        return self.delegate.decide(history)

    def __getattr__(self, name):
        return getattr(self.delegate, name)
