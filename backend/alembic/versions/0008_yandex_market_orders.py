"""Add Yandex Market order packing integration.

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op
from app.modules.integrations.yandex_market.models import MarketOrder, YandexMarketAccount

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bot_columns = {
        column["name"] for column in inspect(bind).get_columns("max_bot_configs")
    }
    if "integration" not in bot_columns:
        op.add_column(
            "max_bot_configs",
            sa.Column(
                "integration", sa.String(length=32), nullable=False, server_default="direct"
            ),
        )
        op.create_index(
            "ix_max_bot_configs_integration", "max_bot_configs", ["integration"]
        )
    access_columns = {
        column["name"] for column in inspect(bind).get_columns("max_access_requests")
    }
    if "role" not in access_columns:
        op.add_column(
            "max_access_requests",
            sa.Column("role", sa.String(length=24), nullable=False, server_default="viewer"),
        )
        op.create_index(
            "ix_max_access_requests_role", "max_access_requests", ["role"]
        )
    YandexMarketAccount.__table__.create(bind=bind, checkfirst=True)
    MarketOrder.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    MarketOrder.__table__.drop(bind=bind, checkfirst=True)
    YandexMarketAccount.__table__.drop(bind=bind, checkfirst=True)
    access_columns = {
        column["name"] for column in inspect(bind).get_columns("max_access_requests")
    }
    if "role" in access_columns:
        op.drop_index("ix_max_access_requests_role", table_name="max_access_requests")
        op.drop_column("max_access_requests", "role")
    bot_columns = {
        column["name"] for column in inspect(bind).get_columns("max_bot_configs")
    }
    if "integration" in bot_columns:
        op.drop_index("ix_max_bot_configs_integration", table_name="max_bot_configs")
        op.drop_column("max_bot_configs", "integration")
