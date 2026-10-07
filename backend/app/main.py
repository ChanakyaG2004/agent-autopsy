import logging
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import Experiment
from app.schemas import ExperimentDraft, ExperimentRead, ExperimentValidation

logger = logging.getLogger(__name__)

app = FastAPI(title="Agent Autopsy API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

DatabaseSession = Annotated[Session, Depends(get_session)]


@app.exception_handler(SQLAlchemyError)
def database_error(request: Request, error: SQLAlchemyError) -> JSONResponse:
    logger.error("Database operation failed: %s", type(error).__name__)
    return JSONResponse(
        status_code=503,
        content={"detail": "Could not complete the database operation. Try again later."},
    )


@app.post("/experiments/validate", response_model=ExperimentValidation)
def validate_experiment(draft: ExperimentDraft) -> ExperimentValidation:
    return ExperimentValidation(
        message=(
            f'Configuration "{draft.name}" is valid for '
            f'{len(draft.scenarios)} scenario(s). Nothing has been saved or run.'
        )
    )


@app.post("/experiments", response_model=ExperimentRead, status_code=201)
def create_experiment(draft: ExperimentDraft, session: DatabaseSession) -> Experiment:
    experiment = Experiment(**draft.model_dump())
    with session.begin():
        session.add(experiment)
        session.flush()
        session.refresh(experiment)
    return experiment


@app.get("/experiments", response_model=list[ExperimentRead])
def list_experiments(
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Experiment]:
    query = (
        select(Experiment)
        .order_by(Experiment.created_at.desc(), Experiment.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(query))


@app.get("/experiments/{experiment_id}", response_model=ExperimentRead)
def get_experiment(experiment_id: UUID, session: DatabaseSession) -> Experiment:
    experiment = session.get(Experiment, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return experiment
