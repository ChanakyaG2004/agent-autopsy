from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Experiment(Base):
    __tablename__ = "experiments"
    __table_args__ = (
        CheckConstraint("length(trim(name)) >= 3", name="experiment_name_length"),
        CheckConstraint("length(trim(agent_version)) >= 1", name="agent_version_length"),
        CheckConstraint("status IN ('draft', 'running', 'completed', 'failed')", name="experiment_status"),
        CheckConstraint(
            "jsonb_typeof(scenarios) = 'array' AND jsonb_array_length(scenarios) BETWEEN 1 AND 3",
            name="experiment_scenario_count",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(80))
    agent_version: Mapped[str] = mapped_column(String(80))
    scenarios: Mapped[list[str]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), server_default=text("'draft'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'completed', 'failed', 'interrupted')", name="run_status"),
        CheckConstraint("mode IN ('demo', 'demo_claim_only', 'demo_reconcile', 'openai', 'ollama')", name="run_mode"),
        CheckConstraint("scenario IN ('normal', 'timeout_after_commit', 'permission_denied')", name="run_scenario"),
        CheckConstraint("NOT fault_injected OR scenario IN ('timeout_after_commit', 'permission_denied')", name="run_fault_scenario"),
        CheckConstraint("evaluation IS NULL OR jsonb_typeof(evaluation) = 'object'", name="run_evaluation_object"),
        CheckConstraint("recovery_evaluation IS NULL OR jsonb_typeof(recovery_evaluation) = 'object'", name="run_recovery_object"),
        CheckConstraint("security_evaluation IS NULL OR jsonb_typeof(security_evaluation) = 'object'", name="run_security_object"),
        CheckConstraint("grounding_evaluation IS NULL OR jsonb_typeof(grounding_evaluation) = 'object'", name="run_grounding_object"),
        CheckConstraint("model_telemetry IS NULL OR (mode IN ('openai', 'ollama') AND jsonb_typeof(model_telemetry) = 'object')", name="run_model_telemetry_object"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    experiment_id: Mapped[UUID] = mapped_column(ForeignKey("experiments.id"), index=True)
    status: Mapped[str] = mapped_column(String(16))
    mode: Mapped[str] = mapped_column(String(16))
    scenario: Mapped[str] = mapped_column(String(32), server_default=text("'normal'"))
    fault_injected: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    model_name: Mapped[str | None] = mapped_column(String(200))
    trace_id: Mapped[str | None] = mapped_column(String(32))
    evaluation: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    recovery_evaluation: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    security_evaluation: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    grounding_evaluation: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    model_telemetry: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    task: Mapped[str] = mapped_column(Text)
    output: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    steps: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    initial_state: Mapped[dict] = mapped_column(JSONB)
    final_state: Mapped[dict] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Benchmark(Base):
    __tablename__ = "benchmarks"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'completed', 'failed')", name="benchmark_status"),
        CheckConstraint("jsonb_typeof(manifest) = 'object'", name="benchmark_manifest_object"),
        CheckConstraint("jsonb_typeof(summary) = 'object'", name="benchmark_summary_object"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    suite_version: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16))
    manifest: Mapped[dict] = mapped_column(JSONB)
    summary: Mapped[dict] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BenchmarkItem(Base):
    __tablename__ = "benchmark_items"
    __table_args__ = (
        UniqueConstraint("benchmark_id", "position", name="benchmark_item_position"),
        UniqueConstraint("benchmark_id", "case_key", "mode", "repetition", name="benchmark_item_cell"),
        CheckConstraint("status IN ('pending', 'running', 'completed', 'failed')", name="benchmark_item_status"),
        CheckConstraint("mode IN ('demo', 'demo_reconcile', 'demo_claim_only')", name="benchmark_item_mode"),
        CheckConstraint("repetition BETWEEN 1 AND 3 AND position >= 0", name="benchmark_item_bounds"),
        CheckConstraint("status <> 'completed' OR run_id IS NOT NULL", name="benchmark_item_result"),
        CheckConstraint("run_id IS NULL OR (run_id = id AND status IN ('completed', 'failed'))", name="benchmark_item_run_identity"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    benchmark_id: Mapped[UUID] = mapped_column(ForeignKey("benchmarks.id"), index=True)
    experiment_id: Mapped[UUID] = mapped_column(ForeignKey("experiments.id"))
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_runs.id"), unique=True)
    position: Mapped[int] = mapped_column(Integer)
    case_key: Mapped[str] = mapped_column(String(80))
    mode: Mapped[str] = mapped_column(String(16))
    repetition: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    error: Mapped[str | None] = mapped_column(Text)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("kind IN ('run', 'benchmark')", name="job_kind"),
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed', 'interrupted')", name="job_status"),
        CheckConstraint("attempts BETWEEN 0 AND 3", name="job_attempts"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="job_payload"),
        CheckConstraint("(kind = 'run' AND experiment_id IS NOT NULL AND run_id IS NOT NULL AND benchmark_id IS NULL) OR (kind = 'benchmark' AND experiment_id IS NULL AND run_id IS NULL AND benchmark_id IS NOT NULL)", name="job_target"),
        CheckConstraint("(status = 'running' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR (status <> 'running' AND lease_token IS NULL AND lease_expires_at IS NULL)", name="job_lease"),
        CheckConstraint("(status IN ('queued', 'running') AND finished_at IS NULL) OR (status IN ('succeeded', 'failed', 'interrupted') AND finished_at IS NOT NULL)", name="job_finished"),
        Index("job_active_experiment", "experiment_id", unique=True,
              postgresql_where=text("kind = 'run' AND status IN ('queued', 'running')")),
        Index("job_queue", "status", "created_at", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    request_id: Mapped[UUID] = mapped_column(unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    execution_fingerprint: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), server_default=text("'queued'"))
    payload: Mapped[dict] = mapped_column(JSONB)
    experiment_id: Mapped[UUID | None] = mapped_column(ForeignKey("experiments.id"), index=True)
    # This identity is reserved before an AgentRun exists; it intentionally has no FK.
    run_id: Mapped[UUID | None] = mapped_column(unique=True)
    benchmark_id: Mapped[UUID | None] = mapped_column(ForeignKey("benchmarks.id"), unique=True)
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    lease_token: Mapped[UUID | None]
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(100))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
