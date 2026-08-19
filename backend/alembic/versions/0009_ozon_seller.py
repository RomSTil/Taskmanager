"""Add Ozon Seller accounts and postings.

Revision ID: 0009
Revises: 0008
"""
from alembic import op

from app.modules.integrations.ozon_seller.models import OzonPosting, OzonSellerAccount


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    OzonSellerAccount.__table__.create(bind=bind, checkfirst=True)
    OzonPosting.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    OzonPosting.__table__.drop(bind=bind, checkfirst=True)
    OzonSellerAccount.__table__.drop(bind=bind, checkfirst=True)
