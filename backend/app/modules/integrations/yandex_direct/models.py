from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ....database import Base
from ....models import TimestampMixin, VersionMixin, new_id, utcnow


class YandexDirectAccount(TimestampMixin, VersionMixin, Base):
    __tablename__ = "yandex_direct_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    client_login: Mapped[str | None] = mapped_column(String(255), nullable=True)
    token_encrypted: Mapped[str] = mapped_column(Text)
    token_hint: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    balance_threshold: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("5000"))
    days_left_threshold: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("3"))
    anomaly_ratio: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("2"))
    monitor_interval_minutes: Mapped[int] = mapped_column(Integer, default=30)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class IntegrationJob(Base):
    __tablename__ = "integration_jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_integration_job_idempotency_key"),
        Index("ix_integration_job_pending", "status", "available_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(80), index=True)
    job_type: Mapped[str] = mapped_column(String(120), index=True)
    account_id: Mapped[str | None] = mapped_column(
        ForeignKey("yandex_direct_accounts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(240))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DirectCampaignSnapshot(Base):
    __tablename__ = "direct_campaign_snapshots"
    __table_args__ = (
        UniqueConstraint("account_id", "campaign_id", name="uq_direct_campaign_account"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("yandex_direct_accounts.id", ondelete="CASCADE"), index=True
    )
    campaign_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40))
    currency: Mapped[str] = mapped_column(String(16))
    balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    uses_shared_account: Mapped[bool] = mapped_column(Boolean, default=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DirectDailyStat(Base):
    __tablename__ = "direct_daily_stats"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "campaign_id",
            "stat_date",
            name="uq_direct_daily_stat",
        ),
        Index("ix_direct_stats_account_date", "account_id", "stat_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("yandex_direct_accounts.id", ondelete="CASCADE"), index=True
    )
    campaign_id: Mapped[int] = mapped_column(BigInteger, index=True)
    campaign_name: Mapped[str] = mapped_column(String(255))
    stat_date: Mapped[date] = mapped_column(Date)
    impressions: Mapped[int] = mapped_column(BigInteger, default=0)
    clicks: Mapped[int] = mapped_column(BigInteger, default=0)
    cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    conversions: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
