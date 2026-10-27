"""allow local Ollama executions and measurements

Revision ID: 463998dc7718
Revises: 53242250fbfc
Create Date: 2026-10-19 19:38:05.319084

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '463998dc7718'
down_revision: Union[str, Sequence[str], None] = '53242250fbfc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint('run_mode', 'agent_runs', type_='check')
    op.create_check_constraint('run_mode', 'agent_runs', "mode IN ('demo', 'demo_claim_only', 'demo_reconcile', 'openai', 'ollama')")
    op.drop_constraint('run_model_telemetry_object', 'agent_runs', type_='check')
    op.create_check_constraint('run_model_telemetry_object', 'agent_runs',
                               "model_telemetry IS NULL OR (mode IN ('openai', 'ollama') AND jsonb_typeof(model_telemetry) = 'object')")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('run_mode', 'agent_runs', type_='check')
    op.create_check_constraint('run_mode', 'agent_runs', "mode IN ('demo', 'demo_claim_only', 'demo_reconcile', 'openai')")
    op.drop_constraint('run_model_telemetry_object', 'agent_runs', type_='check')
    op.create_check_constraint('run_model_telemetry_object', 'agent_runs',
                               "model_telemetry IS NULL OR (mode = 'openai' AND jsonb_typeof(model_telemetry) = 'object')")
