from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MaxBotCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    token: str = Field(min_length=20, max_length=4096)
    integration: Literal["direct", "market"] = "direct"
    allowlist: list[int] = Field(default_factory=list, max_length=100)
    target_type: Literal["chat", "user"] | None = None
    target_id: int | None = None
    enabled: bool = True


class MaxBotUpdate(ApiModel):
    base_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    token: str | None = Field(default=None, min_length=20, max_length=4096)
    integration: Literal["direct", "market"] | None = None
    allowlist: list[int] | None = Field(default=None, max_length=100)
    target_type: Literal["chat", "user"] | None = None
    target_id: int | None = None
    enabled: bool | None = None


class MaxBotRead(ApiModel):
    id: str
    name: str
    token_hint: str
    integration: str
    allowlist: list[int]
    target_type: str | None
    target_id: int | None
    enabled: bool
    last_error: str | None
    version: int
    webhook_url: str
    created_at: datetime
    updated_at: datetime


class MaxBotCreated(MaxBotRead):
    webhook_secret: str
