from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
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


class OzonSellerAccount(TimestampMixin, VersionMixin, Base):
    __tablename__ = "ozon_seller_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    client_id: Mapped[str] = mapped_column(String(120))
    api_key_encrypted: Mapped[str] = mapped_column(Text)
    api_key_hint: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    poll_interval_minutes: Mapped[int] = mapped_column(Integer, default=5)
    baseline_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class OzonPosting(Base):
    __tablename__ = "ozon_postings"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "scheme",
            "posting_number",
            name="uq_ozon_posting_account_scheme_number",
        ),
        Index("ix_ozon_posting_recent", "account_id", "ozon_created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("ozon_seller_accounts.id", ondelete="CASCADE"), index=True
    )
    scheme: Mapped[str] = mapped_column(String(12), index=True)
    posting_number: Mapped[str] = mapped_column(String(160), index=True)
    order_number: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(String(80), index=True)
    products: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(12), default="RUB")
    ozon_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    shipment_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
