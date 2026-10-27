"""create experiments

Revision ID: afe899211765
Revises:
Create Date: 2026-10-18 01:27:10.497756

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'afe899211765'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('experiments',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('agent_version', sa.String(length=80), nullable=False),
    sa.Column('scenarios', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=16), server_default=sa.text("'draft'"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("jsonb_typeof(scenarios) = 'array' AND jsonb_array_length(scenarios) BETWEEN 1 AND 3", name='experiment_scenario_count'),
    sa.CheckConstraint("status = 'draft'", name='experiment_draft_status'),
    sa.CheckConstraint('length(trim(agent_version)) >= 1', name='agent_version_length'),
    sa.CheckConstraint('length(trim(name)) >= 3', name='experiment_name_length'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_experiments_created_at'), 'experiments', ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_experiments_created_at'), table_name='experiments')
    op.drop_table('experiments')
