import time
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select

from ..config import get_settings
from ..database import SessionLocal
from ..models import BotConfig, OutboxMessage
from ..security import decrypt_secret


def deliver_batch() -> int:
    delivered = 0
    with SessionLocal() as session, httpx.Client(timeout=20) as client:
        messages = list(
            session.scalars(
                select(OutboxMessage)
                .where(
                    OutboxMessage.sent_at.is_(None),
                    OutboxMessage.available_at <= datetime.now(UTC),
                )
                .order_by(OutboxMessage.available_at)
                .limit(50)
            )
        )
        for message in messages:
            bot = session.get(BotConfig, message.bot_id)
            if not bot or not bot.enabled:
                message.last_error = "Bot is disabled or missing"
                message.attempts += 1
                message.available_at = datetime.now(UTC) + timedelta(minutes=5)
                continue
            try:
                token = decrypt_secret(bot.token_encrypted)
                response = client.post(
                    f"https://api.telegram.org/bot{token}/{message.method}", json=message.payload
                )
                response.raise_for_status()
                if not response.json().get("ok"):
                    raise RuntimeError(response.text)
                message.sent_at = datetime.now(UTC)
                message.last_error = None
                delivered += 1
            except (httpx.HTTPError, RuntimeError) as exc:
                message.attempts += 1
                message.last_error = str(exc)[:1000]
                delay = min(3600, 2 ** min(message.attempts, 10))
                message.available_at = datetime.now(UTC) + timedelta(seconds=delay)
        session.commit()
    return delivered


def main() -> None:
    print("Taskman Telegram outbox worker started")
    while True:
        deliver_batch()
        time.sleep(get_settings().telegram_poll_seconds)


if __name__ == "__main__":
    main()
