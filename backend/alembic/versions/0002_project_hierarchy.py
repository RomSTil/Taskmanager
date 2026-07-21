"""Add nested workspaces.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
from sqlalchemy import Column, ForeignKey, String, inspect


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("projects")}
    if "parent_id" not in columns:
        op.add_column("projects", Column("parent_id", String(36), nullable=True))
        if bind.dialect.name != "sqlite":
            op.create_foreign_key(
                "fk_projects_parent_id", "projects", "projects", ["parent_id"], ["id"], ondelete="SET NULL"
            )
        op.create_index("ix_projects_parent_id", "projects", ["parent_id"])


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("projects")}
    if "parent_id" in columns:
        op.drop_index("ix_projects_parent_id", table_name="projects")
        if bind.dialect.name != "sqlite":
            op.drop_constraint("fk_projects_parent_id", "projects", type_="foreignkey")
        op.drop_column("projects", "parent_id")
