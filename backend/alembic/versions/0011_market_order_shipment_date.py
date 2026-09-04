"""Add Yandex Market order shipment date.

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("market_orders")}
    indexes = {index["name"] for index in inspect(bind).get_indexes("market_orders")}
    if "shipment_date" not in columns:
        op.add_column("market_orders", sa.Column("shipment_date", sa.Date(), nullable=True))
    if "ix_market_orders_shipment_date" not in indexes:
        op.create_index(
            "ix_market_orders_shipment_date",
            "market_orders",
            ["shipment_date"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("market_orders")}
    indexes = {index["name"] for index in inspect(bind).get_indexes("market_orders")}
    if "ix_market_orders_shipment_date" in indexes:
        op.drop_index("ix_market_orders_shipment_date", table_name="market_orders")
    if "shipment_date" in columns:
        op.drop_column("market_orders", "shipment_date")
