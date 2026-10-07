from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    status: Literal["draft"]
    created_at: datetime
