"""Add Yandex Market order shipment date.

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa

from alembic import op


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("market_orders", sa.Column("shipment_date", sa.Date(), nullable=True))
    op.create_index(
        "ix_market_orders_shipment_date",
        "market_orders",
        ["shipment_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_market_orders_shipment_date", table_name="market_orders")
    op.drop_column("market_orders", "shipment_date")
