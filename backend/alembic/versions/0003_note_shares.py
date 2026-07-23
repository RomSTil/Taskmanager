"""Add shareable public note links.

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "note_shares" not in inspector.get_table_names():
        op.create_table(
            "note_shares",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "note_id",
                sa.String(length=36),
                sa.ForeignKey("note_index.id", ondelete="CASCADE"),
                nullable=False,
                unique=True,
            ),
            sa.Column("token", sa.String(length=64), nullable=False, unique=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        inspector = inspect(bind)

    indexes = {index["name"] for index in inspector.get_indexes("note_shares")}
    if "ix_note_shares_note_id" not in indexes:
        op.create_index("ix_note_shares_note_id", "note_shares", ["note_id"])
    if "ix_note_shares_token" not in indexes:
        op.create_index("ix_note_shares_token", "note_shares", ["token"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "note_shares" in inspector.get_table_names():
        indexes = {index["name"] for index in inspector.get_indexes("note_shares")}
        if "ix_note_shares_token" in indexes:
            op.drop_index("ix_note_shares_token", table_name="note_shares")
        if "ix_note_shares_note_id" in indexes:
            op.drop_index("ix_note_shares_note_id", table_name="note_shares")
        op.drop_table("note_shares")
