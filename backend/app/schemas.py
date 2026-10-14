from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.evaluation import RefundEvaluation
from app.recovery import RecoveryEvaluation
from app.model_telemetry import ModelTelemetry

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


class ExperimentRead(ExperimentDraft):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: Literal["draft", "running", "completed", "failed"]
    created_at: datetime


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["demo", "demo_claim_only", "demo_reconcile", "openai"] = "demo"


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    experiment_id: UUID
    status: Literal["running", "completed", "failed"]
    mode: Literal["demo", "demo_claim_only", "demo_reconcile", "openai"]
    scenario: Scenario
    fault_injected: bool
    model_name: str | None
    trace_id: str | None
    evaluation: RefundEvaluation | None
    recovery_evaluation: RecoveryEvaluation | None
    model_telemetry: ModelTelemetry | None
    task: str
    output: str | None
    error: str | None
    steps: list[dict]
    initial_state: dict
    final_state: dict
    started_at: datetime
    finished_at: datetime | None
