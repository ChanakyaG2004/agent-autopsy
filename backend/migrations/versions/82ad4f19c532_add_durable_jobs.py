"""Durable queue, worker leases, and explicit interrupted executions.

Revision ID: 82ad4f19c532
Revises: 7ba56d892c41
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "82ad4f19c532"
down_revision = "7ba56d892c41"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("run_status", "agent_runs", type_="check")
    op.create_check_constraint("run_status", "agent_runs", "status IN ('running', 'completed', 'failed', 'interrupted')")
    op.create_table("jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("request_id", sa.Uuid(), unique=True, nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("execution_fingerprint", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("experiment_id", sa.Uuid(), sa.ForeignKey("experiments.id")),
        sa.Column("run_id", sa.Uuid(), unique=True),
        sa.Column("benchmark_id", sa.Uuid(), sa.ForeignKey("benchmarks.id"), unique=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("lease_token", sa.Uuid()),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("worker_id", sa.String(100)),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("kind IN ('run', 'benchmark')", name="job_kind"),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed', 'interrupted')", name="job_status"),
        sa.CheckConstraint("attempts BETWEEN 0 AND 3", name="job_attempts"),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name="job_payload"),
        sa.CheckConstraint("(kind = 'run' AND experiment_id IS NOT NULL AND run_id IS NOT NULL AND benchmark_id IS NULL) OR (kind = 'benchmark' AND experiment_id IS NULL AND run_id IS NULL AND benchmark_id IS NOT NULL)", name="job_target"),
        sa.CheckConstraint("(status = 'running' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR (status <> 'running' AND lease_token IS NULL AND lease_expires_at IS NULL)", name="job_lease"),
        sa.CheckConstraint("(status IN ('queued', 'running') AND finished_at IS NULL) OR (status IN ('succeeded', 'failed', 'interrupted') AND finished_at IS NOT NULL)", name="job_finished"),
    )
    op.create_index("ix_jobs_experiment_id", "jobs", ["experiment_id"])
    op.create_index("job_active_experiment", "jobs", ["experiment_id"], unique=True,
                    postgresql_where=sa.text("kind = 'run' AND status IN ('queued', 'running')"))
    op.create_index("job_queue", "jobs", ["status", "created_at", "id"])


def downgrade():
    # Preserve job receipts and interrupted outcomes instead of silently dropping them.
    op.create_check_constraint("job_downgrade_empty", "jobs", "false")
    op.drop_constraint("run_status", "agent_runs", type_="check")
    op.create_check_constraint("run_status", "agent_runs", "status IN ('running', 'completed', 'failed')")
    op.drop_table("jobs")
