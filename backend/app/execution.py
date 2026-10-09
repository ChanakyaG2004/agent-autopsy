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
        result = execute_agent(driver)
        with session.begin():
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
