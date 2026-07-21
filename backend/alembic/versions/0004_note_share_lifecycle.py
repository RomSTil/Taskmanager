"""Add expiration and revocation to public note links.

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("note_shares", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("note_shares", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("note_shares", "revoked_at")
    op.drop_column("note_shares", "expires_at")
