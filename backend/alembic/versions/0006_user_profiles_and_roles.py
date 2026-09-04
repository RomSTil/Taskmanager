"""Add user display names and roles.

Revision ID: 0006_users
Revises: 0005
"""

import sqlalchemy as sa
from sqlalchemy import inspect
from alembic import op


revision = "0006_users"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("users")}
    if "name" not in columns:
        op.add_column(
            "users",
            sa.Column("name", sa.String(length=120), nullable=False, server_default=""),
        )
    if "role" not in columns:
        op.add_column(
            "users",
            sa.Column("role", sa.String(length=32), nullable=False, server_default="administrator"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("users")}
    if "role" in columns:
        op.drop_column("users", "role")
    if "name" in columns:
        op.drop_column("users", "name")
