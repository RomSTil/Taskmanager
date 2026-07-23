import json
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from .models import TaskStatus


def validate_entity_id(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise ValueError("ID must be a UUID") from exc


EntityId = Annotated[str, AfterValidator(validate_entity_id)]
Tag = Annotated[str, Field(min_length=1, max_length=64)]


def validate_json_payload(value: dict[str, Any]) -> dict[str, Any]:
    if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > 65_536:
        raise ValueError("JSON payload is too large")
    return value


JsonPayload = Annotated[dict[str, Any], AfterValidator(validate_json_payload)]


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SetupState(ApiModel):
    setup_required: bool


class SetupRequest(ApiModel):
    username: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=10, max_length=256)


class LoginRequest(ApiModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=256)


class RefreshRequest(ApiModel):
    refresh_token: str = Field(min_length=32, max_length=256)


class UserRead(ApiModel):
    id: str
    username: str
    created_at: datetime


class TokenPair(ApiModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user: UserRead


class ApiTokenCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(
        default_factory=lambda: ["tasks:read", "notes:read"], max_length=20
    )
    expires_at: datetime | None = None


class ApiTokenRead(ApiModel):
    id: str
    name: str
    scopes: list[str]
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


class ApiTokenCreated(ApiTokenRead):
    token: str


class ProjectCreate(ApiModel):
    id: EntityId | None = None
    parent_id: str | None = None
    name: str = Field(min_length=1, max_length=160)
    key: str | None = Field(default=None, min_length=2, max_length=12, pattern=r"^[A-Za-z][A-Za-z0-9_-]+$")
    description: str = Field(default="", max_length=10_000)
    color: str = Field(default="#8b5cf6", pattern=r"^#[0-9a-fA-F]{6}$")


class ProjectUpdate(ApiModel):
    base_version: int
    name: str | None = Field(default=None, min_length=1, max_length=160)
    key: str | None = Field(
        default=None, min_length=2, max_length=12, pattern=r"^[A-Za-z][A-Za-z0-9_-]+$"
    )
    description: str | None = Field(default=None, max_length=10_000)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    parent_id: str | None = None
    archived: bool | None = None


class ProjectRead(ApiModel):
    id: str
    parent_id: str | None
    name: str
    key: str
    description: str
    color: str
    version: int
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ChecklistCreate(ApiModel):
    id: EntityId | None = None
    text: str = Field(min_length=1, max_length=500)
    position: int = 0


class ChecklistUpdate(ApiModel):
    base_version: int
    text: str | None = Field(default=None, min_length=1, max_length=500)
    is_done: bool | None = None
    position: int | None = None


class ChecklistRead(ApiModel):
    id: str
    text: str
    is_done: bool
    position: int
    version: int
    created_at: datetime
    updated_at: datetime


class CommentCreate(ApiModel):
    id: EntityId | None = None
    body_markdown: str = Field(min_length=1, max_length=100_000)
    source: str = Field(default="manual", max_length=32)
    source_data: JsonPayload = Field(default_factory=dict)


class CommentRead(ApiModel):
    id: str
    body_markdown: str
    source: str
    source_data: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class TaskCreate(ApiModel):
    id: EntityId | None = None
    title: str = Field(min_length=1, max_length=300)
    description_markdown: str = Field(default="", max_length=1_000_000)
    project_id: str | None = None
    parent_id: str | None = None
    status: TaskStatus = TaskStatus.inbox
    priority: int = Field(default=1, ge=0, le=3)
    due_at: datetime | None = None
    tags: list[Tag] = Field(default_factory=list, max_length=50)
    source: str = Field(default="manual", max_length=32)
    source_data: JsonPayload = Field(default_factory=dict)


class TaskUpdate(ApiModel):
    base_version: int
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description_markdown: str | None = Field(default=None, max_length=1_000_000)
    project_id: str | None = None
    parent_id: str | None = None
    status: TaskStatus | None = None
    priority: int | None = Field(default=None, ge=0, le=3)
    due_at: datetime | None = None
    tags: list[Tag] | None = Field(default=None, max_length=50)
    archived: bool | None = None


class TaskRead(ApiModel):
    id: str
    title: str
    description_markdown: str
    project_id: str | None
    parent_id: str | None
    sequence: int | None
    status: TaskStatus
    priority: int
    due_at: datetime | None
    completed_at: datetime | None
    tags: list[str]
    source: str
    source_data: dict[str, Any]
    version: int
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    checklist: list[ChecklistRead] = Field(default_factory=list)
    comments: list[CommentRead] = Field(default_factory=list)
    identifier: str


class SavedViewCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    filters: JsonPayload = Field(default_factory=dict)
    position: int = 0


class SavedViewRead(SavedViewCreate):
    id: str
    version: int
    created_at: datetime
    updated_at: datetime


class NoteCreate(ApiModel):
    id: EntityId | None = None
    title: str = Field(min_length=1, max_length=240)
    path: str | None = Field(default=None, max_length=800)
    project_id: str | None = None
    tags: list[Tag] = Field(default_factory=list, max_length=50)
    content_markdown: str = Field(default="", max_length=5_000_000)
    device_id: str | None = None


class NoteUpdate(ApiModel):
    base_revision: int
    title: str | None = Field(default=None, min_length=1, max_length=240)
    path: str | None = Field(default=None, max_length=800)
    project_id: str | None = None
    tags: list[Tag] | None = Field(default=None, max_length=50)
    content_markdown: str = Field(max_length=5_000_000)
    device_id: str | None = None


class NoteIndexRead(ApiModel):
    id: str
    project_id: str | None
    path: str
    title: str
    tags: list[str]
    revision: int
    content_hash: str
    excerpt: str
    size_bytes: int
    deleted_at: datetime | None
    conflict_of_id: str | None
    created_at: datetime
    updated_at: datetime


class NoteRead(NoteIndexRead):
    content_markdown: str


class NoteShareRead(ApiModel):
    token: str
    expires_at: datetime | None
    revoked_at: datetime | None


class NoteShareCreate(ApiModel):
    expires_at: datetime | None = None


class PublicNoteRead(ApiModel):
    title: str
    path: str
    content_markdown: str
    updated_at: datetime


class KnowledgeGraphNode(ApiModel):
    id: str
    kind: Literal["task", "note"]
    title: str
    subtitle: str = ""
    tags: list[str] = Field(default_factory=list)
    status: TaskStatus | None = None
    priority: int | None = None


class KnowledgeGraphEdge(ApiModel):
    source: str
    target: str
    kind: Literal["task_note", "subtask", "note_link"]


class KnowledgeGraphRead(ApiModel):
    nodes: list[KnowledgeGraphNode]
    edges: list[KnowledgeGraphEdge]


class BacklinkRead(ApiModel):
    id: str
    title: str
    path: str
    excerpt: str


class SyncManifest(ApiModel):
    server_time: datetime
    notes: list[NoteIndexRead]


class SyncPush(ApiModel):
    operation_id: str = Field(min_length=8, max_length=80)
    device_id: str = Field(min_length=1, max_length=120)
    id: EntityId | None = None
    path: str = Field(min_length=1, max_length=800)
    base_revision: int = 0
    content_markdown: str = Field(default="", max_length=5_000_000)
    deleted: bool = False
    project_id: str | None = None


class SyncResult(ApiModel):
    status: Literal["applied", "conflict", "duplicate"]
    note: NoteRead | None = None
    conflict: NoteRead | None = None


class DashboardRead(ApiModel):
    inbox: int
    todo: int
    in_progress: int
    blocked: int
    done: int
    overdue: int


class SearchRead(ApiModel):
    tasks: list[TaskRead]
    notes: list[NoteIndexRead]


class WorkspaceBootstrapRead(ApiModel):
    server_time: datetime
    user: UserRead
    users: list[UserRead]
    projects: list[ProjectRead]
    tasks: list[TaskRead]
    views: list[SavedViewRead]
    dashboard: DashboardRead


class BotCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    token: str = Field(min_length=20)
    project_id: str | None = None
    allowlist: list[int] = Field(default_factory=list)
    enabled: bool = True


class BotUpdate(ApiModel):
    base_version: int
    name: str | None = Field(default=None, min_length=1, max_length=120)
    token: str | None = Field(default=None, min_length=20)
    project_id: str | None = None
    allowlist: list[int] | None = None
    enabled: bool | None = None


class BotRead(ApiModel):
    id: str
    name: str
    project_id: str | None
    token_hint: str
    allowlist: list[int]
    enabled: bool
    last_error: str | None
    version: int
    webhook_url: str
    created_at: datetime
    updated_at: datetime


class BotCreated(BotRead):
    webhook_secret: str
