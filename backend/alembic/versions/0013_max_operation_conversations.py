"""Add persisted MAX operation conversations.

Revision ID: 0013
Revises: 0012
"""

from alembic import op

from app.modules.integrations.max_bot.models import MaxOperationConversation


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    MaxOperationConversation.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    MaxOperationConversation.__table__.drop(bind=op.get_bind(), checkfirst=True)
