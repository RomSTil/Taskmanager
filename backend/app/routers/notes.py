import hashlib
import re
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Security, UploadFile, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from ..config import get_settings
from ..database import get_session
from ..dependencies import Principal, get_principal
from ..models import Attachment, NoteIndex, NoteLink, OperationLog, Project, Task
from ..schemas import (
    BacklinkRead,
    NoteCreate,
    NoteIndexRead,
    NoteRead,
    NoteUpdate,
    SearchRead,
    SyncManifest,
    SyncPush,
    SyncResult,
)
from ..services.vault import (
    create_conflict,
    delete_note,
    note_default_path,
    read_note,
    safe_note_path,
    search_notes,
    write_note,
)


router = APIRouter(tags=["knowledge"])


def _note(session: Session, note_id: str, include_deleted: bool = False) -> NoteIndex:
    note = session.get(NoteIndex, note_id)
    if not note or (note.deleted_at and not include_deleted):
        raise HTTPException(status_code=404, detail="Note not found")
    return note


def _read(note: NoteIndex, content: str | None = None) -> NoteRead:
    base = NoteIndexRead.model_validate(note).model_dump()
    return NoteRead(**base, content_markdown=read_note(note) if content is None else content)


def _project_key(session: Session, project_id: str | None) -> str | None:
    if not project_id:
        return None
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project.key


@router.get("/search", response_model=SearchRead)
def global_search(
    query: str,
    _: Annotated[Principal, Security(get_principal, scopes=["tasks:read", "notes:read"])],
    session: Annotated[Session, Depends(get_session)],
    limit: int = Query(default=50, ge=1, le=100),
) -> SearchRead:
    pattern = f"%{query.strip()}%"
    tasks = list(
        session.scalars(
            select(Task)
            .options(selectinload(Task.project), selectinload(Task.checklist), selectinload(Task.comments))
            .where(
                Task.archived_at.is_(None),
                or_(Task.title.ilike(pattern), Task.description_markdown.ilike(pattern)),
            )
            .order_by(Task.updated_at.desc())
            .limit(limit)
        )
    )
    return SearchRead(tasks=tasks, notes=search_notes(session, query)[:limit])


@router.get("/notes", response_model=list[NoteIndexRead])
def list_notes(
    _: Annotated[Principal, Security(get_principal, scopes=["notes:read"])],
    session: Annotated[Session, Depends(get_session)],
    project_id: str | None = None,
    q: str | None = None,
    include_deleted: bool = False,
    limit: int = Query(default=200, ge=1, le=500),
) -> list[NoteIndex]:
    if q:
        notes = search_notes(session, q, include_deleted)
        return [note for note in notes if not project_id or note.project_id == project_id][:limit]
    query = select(NoteIndex).order_by(NoteIndex.updated_at.desc()).limit(limit)
    if not include_deleted:
        query = query.where(NoteIndex.deleted_at.is_(None))
    if project_id:
        query = query.where(NoteIndex.project_id == project_id)
    return list(session.scalars(query))


@router.post("/notes", response_model=NoteRead, status_code=status.HTTP_201_CREATED)
def create_note(
    payload: NoteCreate,
    _: Annotated[Principal, Security(get_principal, scopes=["notes:write"])],
    session: Annotated[Session, Depends(get_session)],
) -> NoteRead:
    project_key = _project_key(session, payload.project_id)
    path = payload.path or note_default_path(payload.title, project_key)
    note, rendered = write_note(
        session,
        title=payload.title,
        path=path,
        content=payload.content_markdown,
        project_id=payload.project_id,
        tags=payload.tags,
        note_id=payload.id,
        base_revision=0,
        device_id=payload.device_id,
    )
    session.commit()
    session.refresh(note)
    return _read(note, rendered)


@router.get("/notes/{note_id}", response_model=NoteRead)
def get_note(
    note_id: str,
    _: Annotated[Principal, Security(get_principal, scopes=["notes:read"])],
    session: Annotated[Session, Depends(get_session)],
) -> NoteRead:
    return _read(_note(session, note_id))


@router.patch("/notes/{note_id}", response_model=NoteRead)
def update_note(
    note_id: str,
    payload: NoteUpdate,
    _: Annotated[Principal, Security(get_principal, scopes=["notes:write"])],
    session: Annotated[Session, Depends(get_session)],
) -> NoteRead:
    current = _note(session, note_id)
    project_id = payload.project_id if "project_id" in payload.model_fields_set else current.project_id
    _project_key(session, project_id)
    note, rendered = write_note(
        session,
        title=payload.title or current.title,
        path=payload.path or current.path,
        content=payload.content_markdown,
        project_id=project_id,
        tags=payload.tags if payload.tags is not None else list(current.tags),
        note_id=current.id,
        base_revision=payload.base_revision,
        device_id=payload.device_id,
    )
    session.commit()
    session.refresh(note)
    return _read(note, rendered)


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def archive_note(
    note_id: str,
    base_revision: int,
    _: Annotated[Principal, Security(get_principal, scopes=["notes:write"])],
    session: Annotated[Session, Depends(get_session)],
) -> None:
    note = _note(session, note_id)
    if note.revision != base_revision:
        raise HTTPException(status_code=409, detail={"current_revision": note.revision})
    delete_note(session, note)
    session.commit()


@router.get("/notes/{note_id}/backlinks", response_model=list[BacklinkRead])
def backlinks(
    note_id: str,
    _: Annotated[Principal, Security(get_principal, scopes=["notes:read"])],
    session: Annotated[Session, Depends(get_session)],
) -> list[BacklinkRead]:
    note = _note(session, note_id)
    sources = session.scalars(
        select(NoteIndex)
        .join(NoteLink, NoteLink.source_note_id == NoteIndex.id)
        .where(NoteLink.target_title == note.title, NoteIndex.deleted_at.is_(None))
        .order_by(NoteIndex.updated_at.desc())
    )
    return [BacklinkRead(id=item.id, title=item.title, path=item.path, excerpt=item.excerpt) for item in sources]


@router.get("/sync/manifest", response_model=SyncManifest)
def sync_manifest(
    _: Annotated[Principal, Security(get_principal, scopes=["notes:read"])],
    session: Annotated[Session, Depends(get_session)],
    changed_since: datetime | None = None,
) -> SyncManifest:
    query = select(NoteIndex).order_by(NoteIndex.updated_at)
    if changed_since:
        query = query.where(NoteIndex.updated_at > changed_since)
    return SyncManifest(server_time=datetime.now(UTC), notes=list(session.scalars(query)))


@router.post("/sync/push", response_model=SyncResult)
def sync_push(
    payload: SyncPush,
    _: Annotated[Principal, Security(get_principal, scopes=["notes:write"])],
    session: Annotated[Session, Depends(get_session)],
) -> SyncResult:
    duplicate = session.get(OperationLog, payload.operation_id)
    if duplicate:
        note = session.get(NoteIndex, duplicate.result.get("note_id"))
        conflict = session.get(NoteIndex, duplicate.result.get("conflict_id"))
        return SyncResult(
            status="duplicate",
            note=_read(note) if note and not note.deleted_at else None,
            conflict=_read(conflict) if conflict else None,
        )
    current = session.get(NoteIndex, payload.id) if payload.id else session.scalar(
        select(NoteIndex).where(NoteIndex.path_key == payload.path.replace("\\", "/").casefold())
    )
    if payload.deleted:
        if not current:
            result = SyncResult(status="applied")
        elif current.revision != payload.base_revision:
            result = SyncResult(status="conflict", note=_read(current))
        else:
            delete_note(session, current, payload.device_id)
            result = SyncResult(status="applied")
        session.add(
            OperationLog(
                operation_id=payload.operation_id,
                entity_type="note.sync",
                entity_id=current.id if current else None,
                result={"note_id": current.id if current else None, "status": result.status},
            )
        )
        session.commit()
        return result

    metadata_title = PurePath(payload.path).stem
    if current and current.revision != payload.base_revision:
        conflict, rendered = create_conflict(
            session, original=current, content=payload.content_markdown, device_id=payload.device_id
        )
        session.add(
            OperationLog(
                operation_id=payload.operation_id,
                entity_type="note.sync",
                entity_id=current.id,
                result={"note_id": current.id, "conflict_id": conflict.id, "status": "conflict"},
            )
        )
        session.commit()
        session.refresh(conflict)
        return SyncResult(status="conflict", note=_read(current), conflict=_read(conflict, rendered))

    parsed_title = metadata_title
    try:
        import frontmatter

        parsed_title = str(frontmatter.loads(payload.content_markdown).get("title") or metadata_title)
    except (ValueError, TypeError):
        pass
    note, rendered = write_note(
        session,
        title=parsed_title,
        path=payload.path,
        content=payload.content_markdown,
        project_id=payload.project_id if payload.project_id is not None else (current.project_id if current else None),
        tags=list(current.tags) if current else [],
        note_id=current.id if current else payload.id,
        base_revision=payload.base_revision,
        device_id=payload.device_id,
    )
    session.add(
        OperationLog(
            operation_id=payload.operation_id,
            entity_type="note.sync",
            entity_id=note.id,
            result={"note_id": note.id, "status": "applied"},
        )
    )
    session.commit()
    session.refresh(note)
    return SyncResult(status="applied", note=_read(note, rendered))


@router.post("/notes/{note_id}/attachments", status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    note_id: str,
    _: Annotated[Principal, Security(get_principal, scopes=["notes:write"])],
    session: Annotated[Session, Depends(get_session)],
    upload: UploadFile = File(...),
) -> dict[str, str | int]:
    note = _note(session, note_id)
    content = await upload.read((get_settings().max_attachment_mb * 1024 * 1024) + 1)
    if len(content) > get_settings().max_attachment_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Attachment is too large")
    safe_name = re.sub(r"[^\w.() -]", "_", PurePath(upload.filename or "attachment").name)
    relative = f"_assets/{note.id}/{safe_name}"
    _, absolute = safe_note_path(relative + ".md")
    absolute = absolute.with_suffix("")
    absolute.parent.mkdir(parents=True, exist_ok=True)
    if absolute.exists():
        safe_name = f"{hashlib.sha256(content).hexdigest()[:8]}-{safe_name}"
        relative = f"_assets/{note.id}/{safe_name}"
        absolute = absolute.parent / safe_name
    absolute.write_bytes(content)
    attachment = Attachment(
        note_id=note.id,
        path=relative,
        filename=safe_name,
        content_type=upload.content_type or "application/octet-stream",
        size_bytes=len(content),
        content_hash=hashlib.sha256(content).hexdigest(),
    )
    session.add(attachment)
    session.commit()
    return {"id": attachment.id, "path": relative, "size_bytes": len(content)}
