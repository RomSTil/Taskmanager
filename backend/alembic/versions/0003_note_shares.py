"""Add shareable public note links.

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "note_shares",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("note_id", sa.String(length=36), sa.ForeignKey("note_index.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("token", sa.String(length=64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_note_shares_note_id", "note_shares", ["note_id"])
    op.create_index("ix_note_shares_token", "note_shares", ["token"])


def downgrade() -> None:
    op.drop_index("ix_note_shares_token", table_name="note_shares")
    op.drop_index("ix_note_shares_note_id", table_name="note_shares")
    op.drop_table("note_shares")
