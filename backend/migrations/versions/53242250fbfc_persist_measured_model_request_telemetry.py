"""persist measured model request telemetry

Revision ID: 53242250fbfc
Revises: cf13a9502ab7
Create Date: 2026-10-19 01:20:55.784128

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '53242250fbfc'
down_revision: Union[str, Sequence[str], None] = 'cf13a9502ab7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('agent_runs', sa.Column('model_telemetry', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True))
    op.create_check_constraint('run_model_telemetry_object', 'agent_runs',
                               "model_telemetry IS NULL OR (mode = 'openai' AND jsonb_typeof(model_telemetry) = 'object')")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_check_constraint('run_downgrade_no_model_telemetry', 'agent_runs', 'model_telemetry IS NULL')
    op.drop_constraint('run_downgrade_no_model_telemetry', 'agent_runs', type_='check')
    op.drop_constraint('run_model_telemetry_object', 'agent_runs', type_='check')
    op.drop_column('agent_runs', 'model_telemetry')
