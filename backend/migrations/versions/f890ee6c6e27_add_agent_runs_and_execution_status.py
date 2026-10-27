"""add agent runs and execution status

Revision ID: f890ee6c6e27
Revises: afe899211765
Create Date: 2026-10-18 01:37:52.226265

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f890ee6c6e27'
down_revision: Union[str, Sequence[str], None] = 'afe899211765'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint('experiment_draft_status', 'experiments', type_='check')
    op.create_check_constraint('experiment_status', 'experiments',
                               "status IN ('draft', 'running', 'completed', 'failed')")
    op.create_table('agent_runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('experiment_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('mode', sa.String(length=16), nullable=False),
    sa.Column('model_name', sa.String(length=200), nullable=True),
    sa.Column('task', sa.Text(), nullable=False),
    sa.Column('output', sa.Text(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('steps', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('initial_state', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('final_state', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("mode IN ('demo', 'openai')", name='run_mode'),
    sa.CheckConstraint("status IN ('running', 'completed', 'failed')", name='run_status'),
    sa.ForeignKeyConstraint(['experiment_id'], ['experiments.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_runs_experiment_id'), 'agent_runs', ['experiment_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('experiment_status', 'experiments', type_='check')
    op.create_check_constraint('experiment_draft_status', 'experiments', "status = 'draft'")
    op.drop_index(op.f('ix_agent_runs_experiment_id'), table_name='agent_runs')
    op.drop_table('agent_runs')
