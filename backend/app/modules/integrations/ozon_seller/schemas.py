from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class OzonAccountCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    client_id: str = Field(min_length=1, max_length=120)
    api_key: str = Field(min_length=10, max_length=4096)
    poll_interval_minutes: int = Field(default=1, ge=1, le=1440)
    enabled: bool = True


class OzonAccountRead(ApiModel):
    id: str
    name: str
    client_id: str
    api_key_hint: str
    enabled: bool
    poll_interval_minutes: int
    baseline_completed: bool
    last_checked_at: datetime | None
    last_error: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class OzonPostingRead(ApiModel):
    id: str
    scheme: str
    posting_number: str
    order_number: str | None
    status: str
    products: list[dict]
    total: Decimal
    currency: str
    ozon_created_at: datetime | None
    shipment_date: datetime | None
    first_seen_at: datetime


class OzonSyncRead(ApiModel):
    account_id: str
    fetched: int
    created: int
    notified: int
    baseline: bool
