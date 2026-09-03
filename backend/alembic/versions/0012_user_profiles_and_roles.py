"""Add user display names and roles.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("name", sa.String(length=120), nullable=False, server_default=""),
    )
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=32), nullable=False, server_default="administrator"),
    )


def downgrade() -> None:
    op.drop_column("users", "role")
    op.drop_column("users", "name")
