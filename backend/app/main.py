from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, field_validator

app = FastAPI(title="Agent Autopsy API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["POST"],
    allow_headers=["Content-Type"],
)

Scenario = Literal["normal", "timeout_after_commit", "permission_denied"]


class ExperimentDraft(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=3, max_length=80)
    agent_version: str = Field(min_length=1, max_length=80)
    scenarios: list[Scenario] = Field(min_length=1, max_length=3)

    @field_validator("scenarios")
    @classmethod
    def reject_duplicates(cls, scenarios: list[Scenario]) -> list[Scenario]:
        if len(scenarios) != len(set(scenarios)):
            raise ValueError("Choose each scenario only once")
        return scenarios


class ExperimentValidation(BaseModel):
    message: str


@app.post("/experiments/validate", response_model=ExperimentValidation)
def validate_experiment(draft: ExperimentDraft) -> ExperimentValidation:
    return ExperimentValidation(
        message=(
            f'Configuration "{draft.name}" is valid for '
            f'{len(draft.scenarios)} scenario(s). Nothing has been saved or run.'
        )
    )
