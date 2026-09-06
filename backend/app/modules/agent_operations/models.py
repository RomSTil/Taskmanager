import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base
from ...models import new_id, utcnow


class AgentRunStatus(str, enum.Enum):
    queued = "queued"
    planning = "planning"
    running = "running"
    internal_review = "internal_review"
    waiting_approval = "waiting_approval"
    waiting_owner_review = "waiting_owner_review"
    revision = "revision"
    accepted = "accepted"
    completed = "completed"
    cancelled = "cancelled"
    failed = "failed"
    blocked = "blocked"


class AgentMode(str, enum.Enum):
    auto = "auto"
    fast = "fast"
    analysis = "analysis"
    maximum = "maximum"


class AgentRole(str, enum.Enum):
    coordinator = "coordinator"
    market_researcher = "market_researcher"
    researcher_developer = "researcher_developer"
    tester = "tester"
    visual_reviewer = "visual_reviewer"
    deploy = "deploy"


class ApprovalStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"


class ApprovalAction(str, enum.Enum):
    external_message = "external_message"
    publication = "publication"
    money = "money"
    destructive = "destructive"


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_status_created", "status", "created_at"),
        Index("ix_agent_runs_task_created", "task_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    parent_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    goal: Mapped[str] = mapped_column(Text)
    status: Mapped[AgentRunStatus] = mapped_column(
        Enum(AgentRunStatus, native_enum=False), default=AgentRunStatus.queued, index=True
    )
    mode: Mapped[AgentMode] = mapped_column(
        Enum(AgentMode, native_enum=False), default=AgentMode.auto
    )
    selected_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    selected_effort: Mapped[str | None] = mapped_column(String(24), nullable=True)
    usage_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    usage_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    usage_reasoning_tokens: Mapped[int] = mapped_column(Integer, default=0)
    role: Mapped[AgentRole] = mapped_column(
        Enum(AgentRole, native_enum=False), default=AgentRole.coordinator
    )
    runner_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_runners.id", ondelete="SET NULL"), nullable=True, index=True
    )
    approval_policy_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    allowed_actions: Mapped[list[str]] = mapped_column(JSON, default=list)
    result_note_id: Mapped[str | None] = mapped_column(
        ForeignKey("note_index.id", ondelete="SET NULL"), nullable=True
    )
    preview_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentRunStep(Base):
    __tablename__ = "agent_run_steps"
    __table_args__ = (Index("ix_agent_run_steps_run_status", "run_id", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    role: Mapped[AgentRole] = mapped_column(Enum(AgentRole, native_enum=False), index=True)
    input_context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    executor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[AgentRunStatus] = mapped_column(
        Enum(AgentRunStatus, native_enum=False), default=AgentRunStatus.queued, index=True
    )
    artifact_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentEvent(Base):
    __tablename__ = "agent_events"
    __table_args__ = (Index("ix_agent_events_run_created", "run_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    step_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_run_steps.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    actor_type: Mapped[str] = mapped_column(String(24), default="system")
    actor_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentApproval(Base):
    __tablename__ = "agent_approvals"
    __table_args__ = (Index("ix_agent_approvals_run_status", "run_id", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    action: Mapped[ApprovalAction] = mapped_column(Enum(ApprovalAction, native_enum=False))
    explanation: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus, native_enum=False), default=ApprovalStatus.pending, index=True
    )
    requested_by_step_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_run_steps.id", ondelete="SET NULL"), nullable=True
    )
    decided_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentRunner(Base):
    __tablename__ = "agent_runners"
    __table_args__ = (Index("ix_agent_runners_online", "enabled", "last_heartbeat_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    version: Mapped[str] = mapped_column(String(80), default="unknown")
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    max_concurrency: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
