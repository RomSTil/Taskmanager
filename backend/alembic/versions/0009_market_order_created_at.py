"""Store the Yandex Market order creation time.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("market_orders")}
    if "market_created_at" not in columns:
        op.add_column(
            "market_orders",
            sa.Column("market_created_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("market_orders")}
    if "market_created_at" in columns:
        op.drop_column("market_orders", "market_created_at")
