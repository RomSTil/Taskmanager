"""Add user access log.

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_access_logs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("client_host", sa.String(length=255), nullable=False, server_default="unknown"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_user_access_logs_user_id", "user_access_logs", ["user_id"])
    op.create_index("ix_user_access_logs_action", "user_access_logs", ["action"])
    op.create_index("ix_user_access_logs_created_at", "user_access_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("user_access_logs")
