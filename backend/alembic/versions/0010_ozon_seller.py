"""Add Ozon Seller accounts and postings.

Revision ID: 0010
Revises: 0009
"""

from alembic import op

from app.modules.integrations.ozon_seller.models import OzonPosting, OzonSellerAccount


revision = "0010"
down_revision = "0009"
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
