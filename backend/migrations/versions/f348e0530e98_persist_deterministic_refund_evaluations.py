"""persist deterministic refund evaluations

Revision ID: f348e0530e98
Revises: 33837c15d947
Create Date: 2026-10-18 16:55:39.279199

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f348e0530e98'
down_revision: Union[str, Sequence[str], None] = '33837c15d947'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('agent_runs', sa.Column('evaluation', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True))
    op.create_check_constraint('run_evaluation_object', 'agent_runs',
                               "evaluation IS NULL OR jsonb_typeof(evaluation) = 'object'")
    op.drop_constraint('run_mode', 'agent_runs', type_='check')
    op.create_check_constraint('run_mode', 'agent_runs',
                               "mode IN ('demo', 'demo_claim_only', 'openai')")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('run_mode', 'agent_runs', type_='check')
    op.create_check_constraint('run_mode', 'agent_runs', "mode IN ('demo', 'openai')")
    op.drop_constraint('run_evaluation_object', 'agent_runs', type_='check')
    op.drop_column('agent_runs', 'evaluation')
