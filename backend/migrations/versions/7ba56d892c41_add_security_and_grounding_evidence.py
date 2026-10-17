"""Persist independent tool-policy and typed-answer grounding checks.

Revision ID: 7ba56d892c41
Revises: 463998dc7718
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "7ba56d892c41"
down_revision = "463998dc7718"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("security", "grounding"):
        op.add_column("agent_runs", sa.Column(f"{name}_evaluation", postgresql.JSONB(none_as_null=True), nullable=True))
        op.create_check_constraint(f"run_{name}_object", "agent_runs",
                                   f"{name}_evaluation IS NULL OR jsonb_typeof({name}_evaluation) = 'object'")


def downgrade():
    # Refuse a lossy downgrade once any new assurance evidence has been saved.
    op.create_check_constraint("run_downgrade_no_assurance", "agent_runs",
                               "security_evaluation IS NULL AND grounding_evaluation IS NULL")
    op.drop_constraint("run_downgrade_no_assurance", "agent_runs", type_="check")
    for name in ("grounding", "security"):
        op.drop_constraint(f"run_{name}_object", "agent_runs", type_="check")
        op.drop_column("agent_runs", f"{name}_evaluation")
