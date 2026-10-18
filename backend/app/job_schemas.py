from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.benchmark_schemas import BenchmarkRequest
from app.schemas import RunRequest


class RunJobRequest(RunRequest):
    request_id: UUID


class BenchmarkJobRequest(BenchmarkRequest):
    request_id: UUID


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    job_version: Literal["durable-jobs-v1"] = "durable-jobs-v1"
    id: UUID
    request_id: UUID
    kind: Literal["run", "benchmark"]
    status: Literal["queued", "running", "succeeded", "failed", "interrupted"]
    experiment_id: UUID | None
    run_id: UUID | None
    benchmark_id: UUID | None
    attempts: int
    worker_id: str | None
    lease_expires_at: datetime | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
