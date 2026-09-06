"""Add agent usage telemetry and Telegram trace subscriptions.

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op

from app.models import TelegramAgentSubscription


revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    TelegramAgentSubscription.__table__.create(bind=bind, checkfirst=True)
    with op.batch_alter_table("agent_runs") as batch:
        batch.add_column(sa.Column("usage_input_tokens", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("usage_output_tokens", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("usage_reasoning_tokens", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_column("usage_reasoning_tokens")
        batch.drop_column("usage_output_tokens")
        batch.drop_column("usage_input_tokens")
    TelegramAgentSubscription.__table__.drop(op.get_bind(), checkfirst=True)
