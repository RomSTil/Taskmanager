import hashlib
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import frontmatter
from fastapi import HTTPException
from sqlalchemy import delete, or_, select, text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import NoteIndex, NoteLink, NoteRevision, new_id


WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
FRONTMATTER_KEYS = {"taskman_id", "title", "project_id", "tags", "revision", "created_at", "updated_at"}


def _root() -> Path:
    root = get_settings().vault_path.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "_assets").mkdir(exist_ok=True)
    (root / ".taskman" / "trash").mkdir(parents=True, exist_ok=True)
    return root


def normalize_path_key(path: str) -> str:
    return unicodedata.normalize("NFC", path).replace("\\", "/").casefold()


def safe_note_path(relative_path: str) -> tuple[str, Path]:
    normalized = unicodedata.normalize("NFC", relative_path.strip()).replace("\\", "/")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or ".." in pure.parts or not normalized:
        raise HTTPException(status_code=422, detail="Unsafe vault path")
    if pure.suffix.lower() != ".md":
        raise HTTPException(status_code=422, detail="Notes must use the .md extension")
    root = _root()
    resolved = (root / Path(*pure.parts)).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Vault path escapes its root") from exc
    return pure.as_posix(), resolved


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip()
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "-", value)
    value = re.sub(r"\s+", " ", value).strip(" .-")
    return value[:120] or "Untitled"


def note_default_path(title: str, project_key: str | None = None) -> str:
    directory = slugify(project_key) if project_key else "Inbox"
    return f"{directory}/{slugify(title)}.md"


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _parse(content: str) -> tuple[dict, str]:
    post = frontmatter.loads(content)
    return dict(post.metadata), post.content


def _render(body: str, metadata: dict) -> str:
    post = frontmatter.Post(body, **metadata)
    return frontmatter.dumps(post) + "\n"


def _metadata(note_id: str, title: str, project_id: str | None, tags: list[str], revision: int, existing: dict | None = None) -> dict:
    now = datetime.now(UTC).isoformat()
    merged = {key: value for key, value in (existing or {}).items() if key not in FRONTMATTER_KEYS}
    merged.update(
        {
            "taskman_id": note_id,
            "title": title,
            "project_id": project_id,
            "tags": tags,
            "revision": revision,
            "created_at": (existing or {}).get("created_at", now),
            "updated_at": now,
        }
    )
    return merged


def _update_links(session: Session, note: NoteIndex, content: str) -> None:
    session.execute(delete(NoteLink).where(NoteLink.source_note_id == note.id))
    targets = {match.strip() for match in WIKILINK_RE.findall(content) if match.strip()}
    session.add_all(NoteLink(source_note_id=note.id, target_title=target) for target in targets)


def _index_values(content: str) -> tuple[str, str]:
    _, body = _parse(content)
    plain = re.sub(r"[`*_>#\[\]()-]", " ", body)
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain[:360], plain


def write_note(
    session: Session,
    *,
    title: str,
    path: str,
    content: str,
    project_id: str | None,
    tags: list[str],
    note_id: str | None = None,
    base_revision: int = 0,
    device_id: str | None = None,
    conflict_of_id: str | None = None,
) -> tuple[NoteIndex, str]:
    relative, absolute = safe_note_path(path)
    existing_note = session.get(NoteIndex, note_id) if note_id else session.scalar(
        select(NoteIndex).where(NoteIndex.path_key == normalize_path_key(relative))
    )
    if existing_note and existing_note.deleted_at is None and existing_note.revision != base_revision:
        raise HTTPException(
            status_code=409,
            detail={"code": "revision_conflict", "current_revision": existing_note.revision},
        )
    if not existing_note:
        duplicate_path = session.scalar(
            select(NoteIndex).where(NoteIndex.path_key == normalize_path_key(relative))
        )
        if duplicate_path and duplicate_path.deleted_at is None:
            raise HTTPException(status_code=409, detail="A note already uses this path")

    parsed_metadata, body = _parse(content)
    if existing_note:
        _, existing_absolute = safe_note_path(existing_note.path)
        if existing_absolute.exists():
            existing_metadata, _ = _parse(existing_absolute.read_text(encoding="utf-8"))
            parsed_metadata = {**existing_metadata, **parsed_metadata}
    stable_id = note_id or (new_id() if conflict_of_id else str(parsed_metadata.get("taskman_id") or new_id()))
    revision = (existing_note.revision + 1) if existing_note else 1
    rendered = _render(
        body,
        _metadata(stable_id, title, project_id, tags, revision, parsed_metadata),
    )
    digest = content_hash(rendered)
    excerpt, searchable = _index_values(rendered)

    absolute.parent.mkdir(parents=True, exist_ok=True)
    temporary = absolute.with_suffix(absolute.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8", newline="\n")
    temporary.replace(absolute)

    note = existing_note or NoteIndex(id=stable_id, path=relative, path_key=normalize_path_key(relative))
    old_path = note.path if existing_note else relative
    note.path = relative
    note.path_key = normalize_path_key(relative)
    note.title = title
    note.project_id = project_id
    note.tags = tags
    note.revision = revision
    note.content_hash = digest
    note.excerpt = excerpt
    note.search_content = searchable
    note.size_bytes = len(rendered.encode("utf-8"))
    note.deleted_at = None
    note.conflict_of_id = conflict_of_id
    if not existing_note:
        session.add(note)
    if existing_note and old_path != relative:
        _, old_absolute = safe_note_path(old_path)
        if old_absolute.exists() and old_absolute != absolute:
            old_absolute.unlink()
    session.flush()
    session.add(
        NoteRevision(
            note_id=note.id,
            revision=revision,
            content_hash=digest,
            content=rendered.encode("utf-8"),
            device_id=device_id,
        )
    )
    _update_links(session, note, rendered)
    session.flush()
    return note, rendered


def read_note(note: NoteIndex) -> str:
    _, absolute = safe_note_path(note.path)
    if note.deleted_at or not absolute.exists():
        raise HTTPException(status_code=404, detail="Note file not found")
    return absolute.read_text(encoding="utf-8")


def delete_note(session: Session, note: NoteIndex, device_id: str | None = None) -> None:
    _, absolute = safe_note_path(note.path)
    note.revision += 1
    note.deleted_at = datetime.now(UTC)
    if absolute.exists():
        trash = _root() / ".taskman" / "trash" / f"{note.id}-r{note.revision}.md"
        absolute.replace(trash)
    session.add(
        NoteRevision(
            note_id=note.id,
            revision=note.revision,
            content_hash=note.content_hash,
            content=b"",
            device_id=device_id,
        )
    )


def create_conflict(
    session: Session,
    *,
    original: NoteIndex,
    content: str,
    device_id: str,
) -> tuple[NoteIndex, str]:
    path = PurePosixPath(original.path)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    conflict_path = path.with_name(f"{path.stem}.conflict-{slugify(device_id)}-{stamp}.md").as_posix()
    metadata, _ = _parse(content)
    title = f"{metadata.get('title') or original.title} (conflict)"
    return write_note(
        session,
        title=title,
        path=conflict_path,
        content=content,
        project_id=original.project_id,
        tags=list(original.tags),
        base_revision=0,
        device_id=device_id,
        conflict_of_id=original.id,
    )


def search_notes(session: Session, query: str, include_deleted: bool = False) -> list[NoteIndex]:
    base = select(NoteIndex).order_by(NoteIndex.updated_at.desc())
    if not include_deleted:
        base = base.where(NoteIndex.deleted_at.is_(None))
    pattern = f"%{query.strip()}%"
    if session.bind and session.bind.dialect.name == "postgresql":
        return list(
            session.scalars(
                base.where(
                    text(
                        "to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(search_content,'')) "
                        "@@ websearch_to_tsquery('simple', :search_query)"
                    )
                ).params(search_query=query)
            )
        )
    return list(
        session.scalars(
            base.where(or_(NoteIndex.title.ilike(pattern), NoteIndex.search_content.ilike(pattern)))
        )
    )
