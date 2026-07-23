"""Add expiration and revocation to public note links.

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("note_shares")}
    if "expires_at" not in columns:
        op.add_column("note_shares", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    if "revoked_at" not in columns:
        op.add_column("note_shares", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("note_shares")}
    if "revoked_at" in columns:
        op.drop_column("note_shares", "revoked_at")
    if "expires_at" in columns:
        op.drop_column("note_shares", "expires_at")
