import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class TaskStatus(str, enum.Enum):
    inbox = "inbox"
    todo = "todo"
    in_progress = "in_progress"
    blocked = "blocked"
    done = "done"


class TokenKind(str, enum.Enum):
    refresh = "refresh"
    api = "api"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class VersionMixin:
    version: Mapped[int] = mapped_column(Integer, default=1)


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class AuthToken(TimestampMixin, Base):
    __tablename__ = "auth_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), default="session")
    kind: Mapped[TokenKind] = mapped_column(Enum(TokenKind, native_enum=False), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Project(TimestampMixin, VersionMixin, Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    key: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(16), default="#8b5cf6")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tasks: Mapped[list["Task"]] = relationship(back_populates="project")
    parent: Mapped["Project | None"] = relationship(remote_side="Project.id", back_populates="children")
    children: Mapped[list["Project"]] = relationship(back_populates="parent")


class Task(TimestampMixin, VersionMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (UniqueConstraint("project_id", "sequence", name="uq_task_project_sequence"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True, index=True
    )
    sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(300), index=True)
    description_markdown: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, native_enum=False), default=TaskStatus.inbox, index=True
    )
    priority: Mapped[int] = mapped_column(Integer, default=1)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(32), default="manual")
    source_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project | None] = relationship(back_populates="tasks")
    parent: Mapped["Task | None"] = relationship(remote_side="Task.id", back_populates="subtasks")
    subtasks: Mapped[list["Task"]] = relationship(back_populates="parent")
    checklist: Mapped[list["ChecklistItem"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="ChecklistItem.position"
    )
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="Comment.created_at"
    )

    @property
    def identifier(self) -> str:
        if self.project and self.sequence:
            return f"{self.project.key}-{self.sequence}"
        return f"INBOX-{self.id[:6].upper()}"


class ChecklistItem(TimestampMixin, VersionMixin, Base):
    __tablename__ = "checklist_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(String(500))
    is_done: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)
    task: Mapped[Task] = relationship(back_populates="checklist")


class Comment(TimestampMixin, Base):
    __tablename__ = "comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    body_markdown: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), default="manual")
    source_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    task: Mapped[Task] = relationship(back_populates="comments")


class SavedView(TimestampMixin, VersionMixin, Base):
    __tablename__ = "saved_views"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    filters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    position: Mapped[int] = mapped_column(Integer, default=0)


class NoteIndex(TimestampMixin, Base):
    __tablename__ = "note_index"
    __table_args__ = (
        Index("ix_note_index_title_path", "title", "path"),
        UniqueConstraint("path_key", name="uq_note_path_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    path: Mapped[str] = mapped_column(String(800))
    path_key: Mapped[str] = mapped_column(String(800))
    title: Mapped[str] = mapped_column(String(240), index=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    excerpt: Mapped[str] = mapped_column(Text, default="")
    search_content: Mapped[str] = mapped_column(Text, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    conflict_of_id: Mapped[str | None] = mapped_column(
        ForeignKey("note_index.id", ondelete="SET NULL"), nullable=True
    )


class TaskNote(Base):
    """A deliberate knowledge connection between a task and a note."""

    __tablename__ = "task_notes"
    __table_args__ = (UniqueConstraint("task_id", "note_id", name="uq_task_note"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    note_id: Mapped[str] = mapped_column(ForeignKey("note_index.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NoteRevision(Base):
    __tablename__ = "note_revisions"
    __table_args__ = (UniqueConstraint("note_id", "revision", name="uq_note_revision"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    note_id: Mapped[str] = mapped_column(ForeignKey("note_index.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    device_id: Mapped[str | None] = mapped_column(String(120), nullable=True)


class NoteLink(Base):
    __tablename__ = "note_links"
    __table_args__ = (UniqueConstraint("source_note_id", "target_title", name="uq_note_link"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_note_id: Mapped[str] = mapped_column(
        ForeignKey("note_index.id", ondelete="CASCADE"), index=True
    )
    target_title: Mapped[str] = mapped_column(String(240), index=True)


class NoteShare(Base):
    __tablename__ = "note_shares"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    note_id: Mapped[str] = mapped_column(
        ForeignKey("note_index.id", ondelete="CASCADE"), unique=True, index=True
    )
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Attachment(TimestampMixin, Base):
    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    note_id: Mapped[str | None] = mapped_column(
        ForeignKey("note_index.id", ondelete="SET NULL"), nullable=True, index=True
    )
    path: Mapped[str] = mapped_column(String(800), unique=True)
    filename: Mapped[str] = mapped_column(String(300))
    content_type: Mapped[str] = mapped_column(String(160))
    size_bytes: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))


class OperationLog(Base):
    __tablename__ = "operation_log"

    operation_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(40), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BotConfig(TimestampMixin, VersionMixin, Base):
    __tablename__ = "bot_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    token_encrypted: Mapped[str] = mapped_column(Text)
    token_hint: Mapped[str] = mapped_column(String(16))
    webhook_secret_hash: Mapped[str] = mapped_column(String(64))
    webhook_secret_encrypted: Mapped[str] = mapped_column(Text)
    allowlist: Mapped[list[int]] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class TelegramUpdate(Base):
    __tablename__ = "telegram_updates"
    __table_args__ = (UniqueConstraint("bot_id", "update_id", name="uq_bot_update"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    bot_id: Mapped[str] = mapped_column(ForeignKey("bot_configs.id", ondelete="CASCADE"))
    update_id: Mapped[int] = mapped_column(Integer)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OutboxMessage(Base):
    __tablename__ = "outbox_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    bot_id: Mapped[str] = mapped_column(ForeignKey("bot_configs.id", ondelete="CASCADE"), index=True)
    chat_id: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(80), default="sendMessage")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
