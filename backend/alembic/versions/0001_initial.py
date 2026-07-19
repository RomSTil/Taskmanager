"""Initial Taskman schema.

Revision ID: 0001
Revises:
"""
from alembic import op

from app.database import Base
from app import models  # noqa: F401


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_note_search_fts ON note_index USING gin "
            "(to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(search_content,'')))"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_task_title_trgm ON tasks USING gin (title gin_trgm_ops)"
        )


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
