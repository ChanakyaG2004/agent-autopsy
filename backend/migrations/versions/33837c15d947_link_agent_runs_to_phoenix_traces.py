"""link agent runs to Phoenix traces

Revision ID: 33837c15d947
Revises: f890ee6c6e27
Create Date: 2026-10-18 14:29:05.129508

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '33837c15d947'
down_revision: Union[str, Sequence[str], None] = 'f890ee6c6e27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('agent_runs', sa.Column('trace_id', sa.String(length=32), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('agent_runs', 'trace_id')
