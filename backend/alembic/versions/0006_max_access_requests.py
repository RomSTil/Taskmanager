"""Add MAX bot access moderation requests.

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

from app.modules.integrations.max_bot.models import MaxAccessRequest


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("max_bot_configs")}
    if "owner_user_id" not in columns:
        op.add_column(
            "max_bot_configs",
            sa.Column("owner_user_id", sa.BigInteger(), nullable=True),
        )
        op.create_index(
            "ix_max_bot_configs_owner_user_id",
            "max_bot_configs",
            ["owner_user_id"],
        )
        op.execute(
            "UPDATE max_bot_configs SET owner_user_id = target_id "
            "WHERE owner_user_id IS NULL AND target_id IS NOT NULL"
        )
    MaxAccessRequest.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    MaxAccessRequest.__table__.drop(bind=bind, checkfirst=True)
    columns = {column["name"] for column in inspect(bind).get_columns("max_bot_configs")}
    if "owner_user_id" in columns:
        op.drop_index("ix_max_bot_configs_owner_user_id", table_name="max_bot_configs")
        op.drop_column("max_bot_configs", "owner_user_id")
