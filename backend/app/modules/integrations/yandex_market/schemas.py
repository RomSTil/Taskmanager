from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MarketAccountCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    campaign_id: int = Field(gt=0)
    api_key: str = Field(min_length=20, max_length=4096)
    enabled: bool = True
    poll_interval_seconds: int = Field(default=60, ge=15, le=3600)


class MarketAccountUpdate(ApiModel):
    base_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    campaign_id: int | None = Field(default=None, gt=0)
    api_key: str | None = Field(default=None, min_length=20, max_length=4096)
    enabled: bool | None = None
    poll_interval_seconds: int | None = Field(default=None, ge=15, le=3600)


class MarketAccountRead(ApiModel):
    id: str
    name: str
    campaign_id: int
    api_key_hint: str
    enabled: bool
    poll_interval_seconds: int
    last_polled_at: datetime | None
    last_error: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class MarketOrderRead(ApiModel):
    id: str
    account_id: str
    market_order_id: int
    status: str
    substatus: str | None
    items: list[dict]
    pack_state: str
    pack_requested_by: int | None
    pack_requested_name: str | None
    pack_requested_at: datetime | None
    packed_at: datetime | None
    pack_error: str | None
    discovered_at: datetime
    last_seen_at: datetime
