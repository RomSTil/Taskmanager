from sqlalchemy import select
from sqlalchemy.orm import Session

from ...event_bus.models import DomainEvent
from ...notifications.service import Notification
from .formatter import notification_payload
from .models import MaxBotConfig, MaxOutboxMessage


class MaxNotificationTransport:
    """MAX transport adapter; it only understands neutral notifications."""

    def enqueue(
        self,
        session: Session,
        event: DomainEvent,
        notification: Notification,
    ) -> int:
        queued = 0
        bots = list(
            session.scalars(
                select(MaxBotConfig).where(
                    MaxBotConfig.enabled.is_(True),
                    MaxBotConfig.target_id.is_not(None),
                    MaxBotConfig.target_type.is_not(None),
                )
            )
        )
        for bot in bots:
            existing = session.scalar(
                select(MaxOutboxMessage.id).where(
                    MaxOutboxMessage.bot_id == bot.id,
                    MaxOutboxMessage.event_id == event.id,
                )
            )
            if existing:
                continue
            session.add(
                MaxOutboxMessage(
                    bot_id=bot.id,
                    event_id=event.id,
                    target_type=str(bot.target_type),
                    target_id=int(bot.target_id or 0),
                    payload=notification_payload(notification),
                )
            )
            queued += 1
        return queued
