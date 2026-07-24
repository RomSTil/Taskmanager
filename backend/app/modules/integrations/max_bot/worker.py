from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....security import decrypt_secret
from .client import MaxApiClient
from .models import MaxBotConfig, MaxOutboxMessage


def deliver_max_messages(
    session: Session,
    *,
    limit: int = 50,
    verify_tls: bool = True,
) -> int:
    now = datetime.now(UTC)
    messages = list(
        session.scalars(
            select(MaxOutboxMessage)
            .where(
                MaxOutboxMessage.sent_at.is_(None),
                MaxOutboxMessage.available_at <= now,
            )
            .order_by(MaxOutboxMessage.available_at)
            .limit(limit)
        )
    )
    delivered = 0
    for message in messages:
        bot = session.get(MaxBotConfig, message.bot_id)
        if bot is None or not bot.enabled:
            message.attempts += 1
            message.last_error = "MAX bot is disabled or missing"
            message.available_at = now + timedelta(minutes=5)
            continue
        try:
            client = MaxApiClient(decrypt_secret(bot.token_encrypted), verify_tls=verify_tls)
            client.send_message(message.target_type, message.target_id, message.payload)
            message.sent_at = datetime.now(UTC)
            message.last_error = None
            bot.last_error = None
            delivered += 1
        except Exception as exc:
            message.attempts += 1
            message.last_error = f"MAX delivery failed ({type(exc).__name__})"
            message.available_at = now + timedelta(
                seconds=min(3600, 2 ** min(message.attempts, 10))
            )
            bot.last_error = message.last_error
    session.commit()
    return delivered
