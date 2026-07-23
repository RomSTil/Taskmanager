from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ....database import Base
from ....models import TimestampMixin, VersionMixin, new_id, utcnow


class MaxBotConfig(TimestampMixin, VersionMixin, Base):
    __tablename__ = "max_bot_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    token_encrypted: Mapped[str] = mapped_column(Text)
    token_hint: Mapped[str] = mapped_column(String(16))
    webhook_secret_hash: Mapped[str] = mapped_column(String(64))
    webhook_secret_encrypted: Mapped[str] = mapped_column(Text)
    allowlist: Mapped[list[int]] = mapped_column(JSON, default=list)
    target_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    target_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class MaxUpdate(Base):
    __tablename__ = "max_updates"
    __table_args__ = (
        UniqueConstraint("bot_id", "update_key", name="uq_max_update_bot_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    bot_id: Mapped[str] = mapped_column(
        ForeignKey("max_bot_configs.id", ondelete="CASCADE"), index=True
    )
    update_key: Mapped[str] = mapped_column(String(64))
    update_type: Mapped[str] = mapped_column(String(80))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MaxOutboxMessage(Base):
    __tablename__ = "max_outbox_messages"
    __table_args__ = (
        UniqueConstraint("bot_id", "event_id", name="uq_max_outbox_bot_event"),
        Index("ix_max_outbox_pending", "sent_at", "available_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    bot_id: Mapped[str] = mapped_column(
        ForeignKey("max_bot_configs.id", ondelete="CASCADE"), index=True
    )
    event_id: Mapped[str | None] = mapped_column(
        ForeignKey("domain_events.id", ondelete="SET NULL"), nullable=True, index=True
    )
    target_type: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[int] = mapped_column(BigInteger)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
