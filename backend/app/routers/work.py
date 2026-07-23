from datetime import UTC, datetime
import re
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Security, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..database import get_session
from ..dependencies import Principal, get_principal
from ..models import (
    ChecklistItem,
    Comment,
    NoteIndex,
    OperationLog,
    Project,
    SavedView,
    Task,
    TaskNote,
    TaskStatus,
    User,
)
from ..schemas import (
    ChecklistCreate,
    ChecklistRead,
    ChecklistUpdate,
    CommentCreate,
    CommentRead,
    DashboardRead,
    ProjectCreate,
    ProjectRead,
    ProjectUpdate,
    SavedViewCreate,
    SavedViewRead,
    TaskCreate,
    TaskRead,
    TaskUpdate,
    NoteIndexRead,
    UserRead,
    WorkspaceBootstrapRead,
)


router = APIRouter(tags=["work"])


def _project(session: Session, project_id: str, *, for_update: bool = False) -> Project:
    query = select(Project).where(Project.id == project_id)
    if for_update:
        query = query.with_for_update()
    item = session.scalar(query)
    if not item:
        raise HTTPException(status_code=404, detail="Project not found")
    return item


def _generated_project_key(session: Session, name: str) -> str:
    """Create a short, stable-looking internal key without asking the user for it."""
    base = re.sub(r"[^A-Za-z0-9]", "", name.upper())[:8] or "WORK"
    if len(base) < 2:
        base = f"WS{base}"
    candidate = base
    number = 2
    while session.scalar(select(Project.id).where(Project.key == candidate)):
        suffix = str(number)
        candidate = f"{base[:12 - len(suffix)]}{suffix}"
        number += 1
    return candidate


def _task(session: Session, task_id: str, *, for_update: bool = False) -> Task:
    query = (
        select(Task)
        .options(selectinload(Task.project), selectinload(Task.checklist), selectinload(Task.comments))
        .where(Task.id == task_id)
    )
    if for_update:
        query = query.with_for_update()
    item = session.scalar(query)
    if not item:
        raise HTTPException(status_code=404, detail="Task not found")
    return item


def _check_version(current: int, base: int) -> None:
    if current != base:
        raise HTTPException(
            status_code=409,
            detail={"code": "version_conflict", "current_version": current},
        )


def _duplicate_operation(session: Session, operation_id: str | None, entity_type: str):
    if not operation_id:
        return None
    operation = session.get(OperationLog, operation_id)
    if operation and operation.entity_type != entity_type:
        raise HTTPException(status_code=409, detail="Operation ID was already used")
    return operation


def _validate_parent(session: Session, task: Task, parent_id: str | None, project_id: str | None) -> None:
    if not parent_id:
        return
    if parent_id == task.id:
        raise HTTPException(status_code=422, detail="Task cannot be its own parent")
    parent = _task(session, parent_id)
    if parent.project_id != project_id:
        raise HTTPException(status_code=422, detail="Parent task must belong to the same project")
    seen = {task.id}
    current: Task | None = parent
    while current:
        if current.id in seen:
            raise HTTPException(status_code=422, detail="Task hierarchy cannot contain a cycle")
        seen.add(current.id)
        current = session.get(Task, current.parent_id) if current.parent_id else None


def _dashboard(session: Session) -> DashboardRead:
    rows = session.execute(
        select(Task.status, func.count(Task.id))
        .where(Task.archived_at.is_(None))
        .group_by(Task.status)
    ).all()
    counts = {value.value: count for value, count in rows}
    overdue = session.scalar(
        select(func.count(Task.id)).where(
            Task.due_at < datetime.now(UTC),
            Task.status != TaskStatus.done,
            Task.archived_at.is_(None),
        )
    )
    return DashboardRead(
        **{value.value: counts.get(value.value, 0) for value in TaskStatus}, overdue=overdue or 0
    )


@router.get("/bootstrap", response_model=WorkspaceBootstrapRead)
def bootstrap_workspace(
    principal: Annotated[
        Principal,
        Security(get_principal, scopes=["projects:read", "tasks:read"]),
    ],
    session: Annotated[Session, Depends(get_session)],
    task_limit: int = Query(default=200, ge=1, le=500),
) -> WorkspaceBootstrapRead:
    projects = list(
        session.scalars(
            select(Project)
            .where(Project.archived_at.is_(None))
            .order_by(Project.created_at)
        )
    )
    tasks = list(
        session.scalars(
            select(Task)
            .options(
                selectinload(Task.project),
                selectinload(Task.checklist),
                selectinload(Task.comments),
            )
            .where(Task.archived_at.is_(None))
            .order_by(Task.updated_at.desc())
            .limit(task_limit)
        )
    )
    views = list(session.scalars(select(SavedView).order_by(SavedView.position, SavedView.name)))
    return WorkspaceBootstrapRead(
        server_time=datetime.now(UTC),
        user=UserRead.model_validate(principal.user),
        users=list(
            session.scalars(select(User).where(User.is_active.is_(True)).order_by(User.username))
        ),
        projects=projects,
        tasks=tasks,
        views=views,
        dashboard=_dashboard(session),
    )


@router.get("/projects", response_model=list[ProjectRead])
def list_projects(
    _: Annotated[Principal, Security(get_principal, scopes=["projects:read"])],
    session: Annotated[Session, Depends(get_session)],
    include_archived: bool = False,
) -> list[Project]:
    query = select(Project).order_by(Project.created_at)
    if not include_archived:
        query = query.where(Project.archived_at.is_(None))
    return list(session.scalars(query))


@router.post("/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    _: Annotated[Principal, Security(get_principal, scopes=["projects:write"])],
    session: Annotated[Session, Depends(get_session)],
) -> Project:
    values = payload.model_dump(exclude={"id"})
    if values.get("parent_id"):
        _project(session, values["parent_id"])
    values["key"] = (values["key"] or _generated_project_key(session, values["name"])).upper()
    project = Project(id=payload.id, **values) if payload.id else Project(**values)
    session.add(project)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Project name, key or ID already exists") from exc
    session.refresh(project)
    return project


@router.patch("/projects/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    _: Annotated[Principal, Security(get_principal, scopes=["projects:write"])],
    session: Annotated[Session, Depends(get_session)],
) -> Project:
    project = _project(session, project_id, for_update=True)
    _check_version(project.version, payload.base_version)
    changes = payload.model_dump(exclude_unset=True, exclude={"base_version", "archived"})
    if "parent_id" in changes and changes["parent_id"]:
        if changes["parent_id"] == project.id:
            raise HTTPException(status_code=422, detail="Workspace cannot be its own parent")
        _project(session, changes["parent_id"])
    if changes.get("key"):
        changes["key"] = changes["key"].upper()
    for key, value in changes.items():
        setattr(project, key, value)
    if payload.archived is not None:
        project.archived_at = datetime.now(UTC) if payload.archived else None
        if payload.archived:
            pending = [project.id]
            while pending:
                children = list(session.scalars(select(Project).where(Project.parent_id.in_(pending))))
                pending = []
                for child in children:
                    if not child.archived_at:
                        child.archived_at = project.archived_at
                        child.version += 1
                    pending.append(child.id)
    project.version += 1
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Project name or key already exists") from exc
    session.refresh(project)
    return project


@router.get("/tasks", response_model=list[TaskRead])
def list_tasks(
    _: Annotated[Principal, Security(get_principal, scopes=["tasks:read"])],
    session: Annotated[Session, Depends(get_session)],
    project_id: str | None = None,
    task_status: TaskStatus | None = Query(default=None, alias="status"),
    parent_id: str | None = None,
    q: str | None = Query(default=None, max_length=200),
    include_archived: bool = False,
    limit: int = Query(default=200, ge=1, le=500),
) -> list[Task]:
    query = (
        select(Task)
        .options(selectinload(Task.project), selectinload(Task.checklist), selectinload(Task.comments))
        .order_by(Task.created_at.desc())
        .limit(limit)
    )
    if not include_archived:
        query = query.where(Task.archived_at.is_(None))
    if project_id:
        query = query.where(Task.project_id == project_id)
    if task_status:
        query = query.where(Task.status == task_status)
    if parent_id:
        query = query.where(Task.parent_id == parent_id)
    if q:
        pattern = f"%{q.strip()}%"
        query = query.where(or_(Task.title.ilike(pattern), Task.description_markdown.ilike(pattern)))
    return list(session.scalars(query))


@router.post("/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreate,
    principal: Annotated[Principal, Security(get_principal, scopes=["tasks:write"])],
    session: Annotated[Session, Depends(get_session)],
    operation_id: Annotated[
        str | None, Header(alias="X-Operation-Id", min_length=8, max_length=80)
    ] = None,
) -> Task:
    duplicate = _duplicate_operation(session, operation_id, "task.create")
    if duplicate and duplicate.entity_id:
        return _task(session, duplicate.entity_id)
    if payload.project_id:
        _project(session, payload.project_id)
    if payload.parent_id:
        parent = _task(session, payload.parent_id)
        if parent.project_id != payload.project_id:
            raise HTTPException(
                status_code=422, detail="Parent task must belong to the same project"
            )
    sequence = None
    if payload.project_id:
        session.execute(select(Project.id).where(Project.id == payload.project_id).with_for_update())
        sequence = (session.scalar(select(func.max(Task.sequence)).where(Task.project_id == payload.project_id)) or 0) + 1
    values = payload.model_dump(exclude={"id"})
    source_data = dict(values.get("source_data") or {})
    source_data["created_by_user_id"] = principal.user.id
    source_data["created_by_username"] = principal.user.username
    assignee_id = source_data.get("assignee_user_id")
    if assignee_id:
        assignee = session.get(User, assignee_id)
        if not assignee or not assignee.is_active:
            raise HTTPException(status_code=422, detail="Assignee is not an active user")
        source_data["assignee_username"] = assignee.username
    values["source_data"] = source_data
    task = Task(id=payload.id, sequence=sequence, **values) if payload.id else Task(sequence=sequence, **values)
    session.add(task)
    if operation_id:
        session.add(OperationLog(operation_id=operation_id, entity_type="task.create", entity_id=task.id))
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if payload.id:
            existing = session.get(Task, payload.id)
            if existing:
                return _task(session, existing.id)
        raise HTTPException(status_code=409, detail="Task ID or operation already exists") from exc
    return _task(session, task.id)


@router.get("/tasks/{task_id}", response_model=TaskRead)
def get_task(
    task_id: str,
    _: Annotated[Principal, Security(get_principal, scopes=["tasks:read"])],
    session: Annotated[Session, Depends(get_session)],
) -> Task:
    return _task(session, task_id)


@router.get("/tasks/{task_id}/notes", response_model=list[NoteIndexRead])
def list_task_notes(
    task_id: str,
    _: Annotated[Principal, Security(get_principal, scopes=["tasks:read", "notes:read"])],
    session: Annotated[Session, Depends(get_session)],
) -> list[NoteIndex]:
    _task(session, task_id)
    return list(
        session.scalars(
            select(NoteIndex)
            .join(TaskNote, TaskNote.note_id == NoteIndex.id)
            .where(TaskNote.task_id == task_id, NoteIndex.deleted_at.is_(None))
            .order_by(TaskNote.created_at.desc())
        )
    )


@router.post("/tasks/{task_id}/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def link_task_note(
    task_id: str,
    note_id: str,
    _: Annotated[Principal, Security(get_principal, scopes=["tasks:write", "notes:read"])],
    session: Annotated[Session, Depends(get_session)],
) -> None:
    _task(session, task_id)
    note = session.get(NoteIndex, note_id)
    if not note or note.deleted_at:
        raise HTTPException(status_code=404, detail="Note not found")
    exists = session.scalar(select(TaskNote).where(TaskNote.task_id == task_id, TaskNote.note_id == note_id))
    if not exists:
        session.add(TaskNote(task_id=task_id, note_id=note_id))
        session.commit()


@router.delete("/tasks/{task_id}/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_task_note(
    task_id: str,
    note_id: str,
    _: Annotated[Principal, Security(get_principal, scopes=["tasks:write", "notes:read"])],
    session: Annotated[Session, Depends(get_session)],
) -> None:
    _task(session, task_id)
    link = session.scalar(select(TaskNote).where(TaskNote.task_id == task_id, TaskNote.note_id == note_id))
    if not link:
        raise HTTPException(status_code=404, detail="Task-note link not found")
    session.delete(link)
    session.commit()


@router.patch("/tasks/{task_id}", response_model=TaskRead)
def update_task(
    task_id: str,
    payload: TaskUpdate,
    _: Annotated[Principal, Security(get_principal, scopes=["tasks:write"])],
    session: Annotated[Session, Depends(get_session)],
    operation_id: Annotated[
        str | None, Header(alias="X-Operation-Id", min_length=8, max_length=80)
    ] = None,
) -> Task:
    duplicate = _duplicate_operation(session, operation_id, "task.update")
    if duplicate and duplicate.entity_id:
        return _task(session, duplicate.entity_id)
    task = _task(session, task_id, for_update=True)
    _check_version(task.version, payload.base_version)
    changes = payload.model_dump(exclude_unset=True, exclude={"base_version", "archived"})
    target_project_id = changes.get("project_id", task.project_id)
    target_parent_id = changes.get("parent_id", task.parent_id)
    if target_project_id:
        _project(session, target_project_id)
    _validate_parent(session, task, target_parent_id, target_project_id)
    if "project_id" in changes and changes["project_id"] != task.project_id:
        if target_project_id:
            _project(session, target_project_id, for_update=True)
            task.sequence = (
                session.scalar(
                    select(func.max(Task.sequence)).where(Task.project_id == target_project_id)
                )
                or 0
            ) + 1
        else:
            task.sequence = None
    for key, value in changes.items():
        setattr(task, key, value)
    if payload.status is not None:
        task.completed_at = datetime.now(UTC) if payload.status == TaskStatus.done else None
    if payload.archived is not None:
        task.archived_at = datetime.now(UTC) if payload.archived else None
    task.version += 1
    if operation_id:
        session.add(OperationLog(operation_id=operation_id, entity_type="task.update", entity_id=task.id))
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Task update conflicts with current data") from exc
    return _task(session, task.id)


@router.post("/tasks/{task_id}/comments", response_model=CommentRead, status_code=201)
def add_comment(
    task_id: str,
    payload: CommentCreate,
    _: Annotated[Principal, Security(get_principal, scopes=["tasks:write"])],
    session: Annotated[Session, Depends(get_session)],
) -> Comment:
    _task(session, task_id)
    values = payload.model_dump(exclude={"id"})
    comment = Comment(id=payload.id, task_id=task_id, **values) if payload.id else Comment(task_id=task_id, **values)
    session.add(comment)
    session.commit()
    session.refresh(comment)
    return comment


@router.post("/tasks/{task_id}/checklist", response_model=ChecklistRead, status_code=201)
def add_checklist_item(
    task_id: str,
    payload: ChecklistCreate,
    _: Annotated[Principal, Security(get_principal, scopes=["tasks:write"])],
    session: Annotated[Session, Depends(get_session)],
) -> ChecklistItem:
    _task(session, task_id)
    values = payload.model_dump(exclude={"id"})
    item = ChecklistItem(id=payload.id, task_id=task_id, **values) if payload.id else ChecklistItem(task_id=task_id, **values)
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.patch("/checklist/{item_id}", response_model=ChecklistRead)
def update_checklist_item(
    item_id: str,
    payload: ChecklistUpdate,
    _: Annotated[Principal, Security(get_principal, scopes=["tasks:write"])],
    session: Annotated[Session, Depends(get_session)],
) -> ChecklistItem:
    item = session.scalar(
        select(ChecklistItem).where(ChecklistItem.id == item_id).with_for_update()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Checklist item not found")
    _check_version(item.version, payload.base_version)
    for key, value in payload.model_dump(exclude_unset=True, exclude={"base_version"}).items():
        setattr(item, key, value)
    item.version += 1
    session.commit()
    session.refresh(item)
    return item


@router.get("/views", response_model=list[SavedViewRead])
def list_views(
    _: Annotated[Principal, Security(get_principal, scopes=["tasks:read"])],
    session: Annotated[Session, Depends(get_session)],
) -> list[SavedView]:
    return list(session.scalars(select(SavedView).order_by(SavedView.position, SavedView.name)))


@router.post("/views", response_model=SavedViewRead, status_code=201)
def create_view(
    payload: SavedViewCreate,
    _: Annotated[Principal, Security(get_principal, scopes=["tasks:write"])],
    session: Annotated[Session, Depends(get_session)],
) -> SavedView:
    view = SavedView(**payload.model_dump())
    session.add(view)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Saved view name already exists") from exc
    session.refresh(view)
    return view


@router.get("/dashboard", response_model=DashboardRead)
def dashboard(
    _: Annotated[Principal, Security(get_principal, scopes=["tasks:read"])],
    session: Annotated[Session, Depends(get_session)],
) -> DashboardRead:
    return _dashboard(session)
