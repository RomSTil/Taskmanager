"""Clear chat IDs incorrectly stored as MAX owner user IDs.

Revision ID: 0007
Revises: 0006
"""
from alembic import op


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE max_bot_configs SET owner_user_id = NULL "
        "WHERE target_type = 'chat' AND owner_user_id = target_id"
    )


def downgrade() -> None:
    # A chat ID cannot safely be reconstructed as a MAX user ID.
    pass
