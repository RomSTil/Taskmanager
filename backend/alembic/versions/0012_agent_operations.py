"""Add autonomous Codex agent operations.

Revision ID: 0012
Revises: 0011
"""

from alembic import op

from app.modules.agent_operations.models import (
    AgentApproval,
    AgentEvent,
    AgentRun,
    AgentRunStep,
    AgentRunner,
)


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create tables idempotently.

    The historic initial migration calls ``Base.metadata.create_all``. Importing
    current models can therefore create these tables before this revision runs
    on a fresh database, while a real upgraded database needs this revision to
    create them. ``checkfirst`` supports both paths safely.
    """
    bind = op.get_bind()
    for table in (
        AgentRunner.__table__,
        AgentRun.__table__,
        AgentRunStep.__table__,
        AgentEvent.__table__,
        AgentApproval.__table__,
    ):
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in (
        AgentApproval.__table__,
        AgentEvent.__table__,
        AgentRunStep.__table__,
        AgentRun.__table__,
        AgentRunner.__table__,
    ):
        table.drop(bind=bind, checkfirst=True)
