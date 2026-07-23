from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DirectAccountCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    token: str = Field(min_length=20, max_length=4096)
    client_login: str | None = Field(default=None, max_length=255)
    balance_threshold: Decimal = Field(default=Decimal("5000"), ge=0)
    days_left_threshold: Decimal = Field(default=Decimal("3"), ge=0, le=365)
    anomaly_ratio: Decimal = Field(default=Decimal("2"), ge=1, le=100)
    monitor_interval_minutes: int = Field(default=30, ge=5, le=1440)
    enabled: bool = True


class DirectAccountUpdate(ApiModel):
    base_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    token: str | None = Field(default=None, min_length=20, max_length=4096)
    client_login: str | None = Field(default=None, max_length=255)
    balance_threshold: Decimal | None = Field(default=None, ge=0)
    days_left_threshold: Decimal | None = Field(default=None, ge=0, le=365)
    anomaly_ratio: Decimal | None = Field(default=None, ge=1, le=100)
    monitor_interval_minutes: int | None = Field(default=None, ge=5, le=1440)
    enabled: bool | None = None


class DirectAccountRead(ApiModel):
    id: str
    name: str
    client_login: str | None
    token_hint: str
    enabled: bool
    balance_threshold: Decimal
    days_left_threshold: Decimal
    anomaly_ratio: Decimal
    monitor_interval_minutes: int
    last_checked_at: datetime | None
    last_error: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class DirectJobRead(ApiModel):
    id: str
    provider: str
    job_type: str
    account_id: str | None
    status: str
    payload: dict
    result: dict
    attempts: int
    available_at: datetime
    started_at: datetime | None
    executed_at: datetime | None
    error: str | None
    created_at: datetime


class DirectCampaignRead(ApiModel):
    campaign_id: int
    name: str
    state: str
    status: str
    currency: str
    balance: Decimal | None
    uses_shared_account: bool
    checked_at: datetime


class DirectDailyStatRead(ApiModel):
    campaign_id: int
    campaign_name: str
    stat_date: date
    impressions: int
    clicks: int
    cost: Decimal
    conversions: Decimal


class DirectJobCreate(ApiModel):
    job_type: Literal["balance_check", "campaign_sync", "report"]
    date_from: date | None = None
    date_to: date | None = None
