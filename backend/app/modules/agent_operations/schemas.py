from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from .models import AgentMode, AgentRole, AgentRunStatus, ApprovalAction, ApprovalStatus


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AgentRunCreate(ApiModel):
    task_id: str
    goal: str = Field(min_length=1, max_length=20_000)
    mode: AgentMode = AgentMode.auto
    allowed_actions: list[Literal["research", "browser", "code_preview"]] = Field(
        default_factory=lambda: ["research"], max_length=3
    )
    parent_run_id: str | None = None
    approval_policy_id: str | None = Field(default=None, max_length=120)


class AgentRunFeedback(ApiModel):
    message: str = Field(min_length=1, max_length=20_000)
    labels: list[Literal["too_template", "off_brand", "logic", "bug"]] = Field(
        default_factory=list, max_length=4
    )


class ApprovalDecision(ApiModel):
    decision: Literal["approved", "rejected"]


class AgentEventCreate(ApiModel):
    event_type: Literal[
        "progress", "role_started", "role_completed", "approval_requested", "blocked", "failed"
    ]
    summary: str = Field(default="", max_length=10_000)
    payload: dict[str, Any] = Field(default_factory=dict)
    step_id: str | None = None


class AgentRunComplete(ApiModel):
    outcome: Literal["owner_review", "internal_review", "completed", "blocked", "failed"] = "owner_review"
    summary: str = Field(default="", max_length=20_000)
    result_note_id: str | None = None
    preview_url: HttpUrl | None = None
    error_code: str | None = Field(default=None, max_length=80)
    error_message: str | None = Field(default=None, max_length=10_000)


class AgentRunnerRegister(ApiModel):
    name: str = Field(min_length=1, max_length=160)
    public_key: str | None = Field(default=None, max_length=20_000)
    version: str = Field(default="unknown", min_length=1, max_length=80)
    capabilities: list[Literal["browser", "git", "docker", "codex"]] = Field(
        default_factory=list, max_length=10
    )
    max_concurrency: int = Field(default=1, ge=1, le=8)


class AgentRunnerHeartbeat(ApiModel):
    version: str | None = Field(default=None, min_length=1, max_length=80)
    capabilities: list[Literal["browser", "git", "docker", "codex"]] | None = Field(
        default=None, max_length=10
    )
    last_error: str | None = Field(default=None, max_length=2_000)


class AgentRunStepRead(ApiModel):
    id: str
    role: AgentRole
    input_context: dict[str, Any]
    executor: str | None
    status: AgentRunStatus
    artifact_url: str | None
    attempts: int
    started_at: datetime | None
    finished_at: datetime | None


class AgentEventRead(ApiModel):
    id: str
    step_id: str | None
    event_type: str
    summary: str
    payload: dict[str, Any]
    actor_type: str
    actor_id: str | None
    created_at: datetime


class AgentApprovalRead(ApiModel):
    id: str
    action: ApprovalAction
    explanation: str
    details: dict[str, Any]
    status: ApprovalStatus
    idempotency_key: str
    decided_at: datetime | None
    expires_at: datetime | None
    created_at: datetime


class AgentRunRead(ApiModel):
    id: str
    task_id: str
    parent_run_id: str | None
    goal: str
    status: AgentRunStatus
    mode: AgentMode
    selected_model: str | None
    selected_effort: str | None
    role: AgentRole
    runner_id: str | None
    approval_policy_id: str | None
    allowed_actions: list[str]
    result_note_id: str | None
    preview_url: str | None
    result_summary: str | None
    error_code: str | None
    error_message: str | None
    lease_expires_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    steps: list[AgentRunStepRead] = Field(default_factory=list)
    events: list[AgentEventRead] = Field(default_factory=list)
    approvals: list[AgentApprovalRead] = Field(default_factory=list)


class AgentRunnerRead(ApiModel):
    id: str
    name: str
    version: str
    capabilities: list[str]
    max_concurrency: int
    enabled: bool
    online: bool
    last_heartbeat_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class AgentRunnerRegistered(AgentRunnerRead):
    runner_token: str


class AgentRunnerControl(ApiModel):
    cancelled_run_ids: list[str] = Field(default_factory=list)


class AgentAssignment(ApiModel):
    run: AgentRunRead
    assignment_token: str
    lease_expires_at: datetime
