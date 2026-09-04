"""Add user access log.

Revision ID: 0007_user_access
Revises: 0006_users
"""

from alembic import op

from app.models import UserAccessLog


revision = "0007_user_access"
down_revision = "0006_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    UserAccessLog.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    UserAccessLog.__table__.drop(bind=op.get_bind(), checkfirst=True)
