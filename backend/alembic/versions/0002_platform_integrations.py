"""Event bus, Yandex Direct provider and MAX transport.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

from app.modules.event_bus.models import DomainEvent
from app.modules.integrations.max_bot.models import (
    MaxBotConfig,
    MaxOutboxMessage,
    MaxUpdate,
)
from app.modules.integrations.yandex_direct.models import (
    DirectCampaignSnapshot,
    DirectDailyStat,
    IntegrationJob,
    YandexDirectAccount,
)


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


TABLES = (
    DomainEvent.__table__,
    YandexDirectAccount.__table__,
    IntegrationJob.__table__,
    DirectCampaignSnapshot.__table__,
    DirectDailyStat.__table__,
    MaxBotConfig.__table__,
    MaxUpdate.__table__,
    MaxOutboxMessage.__table__,
)


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind=bind, checkfirst=True)
