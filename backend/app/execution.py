"""Short database transactions around synchronous execution, never around model calls."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.agent import TASK, execute_agent
from app.models import AgentRun, Experiment
from app.providers import ProviderNotConfigured, make_driver
from app.tools import RefundSandbox
from app.telemetry import mark_failure, set_json, span, trace_id


def start_run(experiment_id: UUID, mode: str, session: Session) -> AgentRun:
    # Validate configuration before claiming the experiment or doing paid work.
    with session.begin():
        experiment = session.get(Experiment, experiment_id)
        if experiment is None:
            raise HTTPException(404, "Experiment not found")
        if experiment.agent_version != "refund-v1" or experiment.scenarios != ["normal"]:
            raise HTTPException(409, "Execution currently supports refund-v1 with only the normal scenario.")
    try:
        driver, model_name = make_driver(mode)
    except ProviderNotConfigured as exc:
        raise HTTPException(503, str(exc)) from None
    try:
        with session.begin():
            claimed = session.execute(
                update(Experiment)
                .where(Experiment.id == experiment_id, Experiment.status != "running")
                .values(status="running")
            ).rowcount
            if not claimed:
                raise HTTPException(409, "This experiment already has a running execution.")
            state = RefundSandbox().snapshot()
            run = AgentRun(experiment_id=experiment_id, mode=mode, model_name=model_name,
                           status="running", task=TASK, initial_state=state, final_state=state)
            session.add(run)
            session.flush()
            session.refresh(run)
        with span("agent.run", "AGENT", **{
            "agent.run_id": str(run.id), "agent.experiment_id": str(experiment_id),
            "agent.mode": mode, "agent.version": experiment.agent_version,
        }) as run_span:
            captured_trace_id = trace_id(run_span)
            set_json(run_span, "input", {"task": TASK})
            result = execute_agent(driver)
            run_span.set_attribute("agent.execution_status", result.status)
            set_json(run_span, "output", {
                "execution_status": result.status,
                "refunded_cents": result.final_state["refunded_cents"],
                "refund_count": len(result.final_state["refunds"]),
            })
            if result.error:
                mark_failure(run_span, result.error)
            with session.begin():
                run.trace_id = captured_trace_id
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
