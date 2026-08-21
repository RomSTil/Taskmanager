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


class YandexMarketAccount(TimestampMixin, VersionMixin, Base):
    __tablename__ = "yandex_market_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    campaign_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    api_key_encrypted: Mapped[str] = mapped_column(Text)
    api_key_hint: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    poll_interval_seconds: Mapped[int] = mapped_column(Integer, default=60)
    last_polled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class MarketOrder(Base):
    __tablename__ = "market_orders"
    __table_args__ = (
        UniqueConstraint("account_id", "market_order_id", name="uq_market_order_account"),
        Index("ix_market_order_queue", "status", "substatus", "pack_state"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("yandex_market_accounts.id", ondelete="CASCADE"), index=True
    )
    market_order_id: Mapped[int] = mapped_column(BigInteger, index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    substatus: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    market_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pack_state: Mapped[str] = mapped_column(String(24), default="available", index=True)
    pack_requested_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    pack_requested_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    pack_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pack_attempts: Mapped[int] = mapped_column(Integer, default=0)
    packed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pack_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
