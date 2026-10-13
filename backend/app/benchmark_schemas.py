from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas import RunRead

DemoMode = Literal["demo", "demo_reconcile", "demo_claim_only"]


class BenchmarkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suite_version: Literal["refund-resilience-v1"] = "refund-resilience-v1"
    repetitions: int = Field(default=1, ge=1, le=3, strict=True)


class BenchmarkCounts(BaseModel):
    planned: int = 0
    recorded: int = 0
    infrastructure_failed: int = 0
    pending: int = 0
    execution_completed: int = 0
    execution_failed: int = 0
    ledger_passed: int = 0
    ledger_failed: int = 0
    ledger_not_evaluable: int = 0
    recovery_passed: int = 0
    recovery_failed: int = 0
    recovery_not_evaluable: int = 0
    recovery_not_applicable: int = 0
    fault_selected: int = 0
    fault_injected: int = 0


class DriverSummary(BaseModel):
    mode: DemoMode
    counts: BenchmarkCounts


class BenchmarkSummary(BaseModel):
    summary_version: Literal["benchmark-counts-v1"] = "benchmark-counts-v1"
    overall: BenchmarkCounts
    drivers: list[DriverSummary]


class BenchmarkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    suite_version: str
    status: Literal["running", "completed", "failed"]
    summary: BenchmarkSummary
    started_at: datetime
    finished_at: datetime | None


class BenchmarkItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    experiment_id: UUID
    run_id: UUID | None
    position: int
    case_key: str
    mode: DemoMode
    repetition: int
    status: Literal["pending", "running", "completed", "failed"]
    error: str | None
    run: RunRead | None


class BenchmarkDetail(BenchmarkRead):
    manifest: dict
    items: list[BenchmarkItemRead]
