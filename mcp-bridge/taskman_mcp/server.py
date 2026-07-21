from typing import Any, Literal

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .config import load_config


mcp = FastMCP("Taskman", json_response=True)
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)


def _request(method: str, path: str, **kwargs: Any) -> Any:
    api_url, token = load_config()
    try:
        response = httpx.request(
            method,
            f"{api_url}/api/v1{path}",
            headers={"Authorization": f"Bearer {token}", **kwargs.pop("headers", {})},
            timeout=20,
            **kwargs,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ValueError(f"Taskman API error ({exc.response.status_code}): {exc.response.text}") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Taskman API is unavailable: {exc}") from exc
    return None if response.status_code == 204 else response.json()


@mcp.tool(annotations=READ)
def list_projects(include_archived: bool = False) -> list[dict[str, Any]]:
    """List Taskman projects."""
    return _request("GET", "/projects", params={"include_archived": include_archived})


@mcp.tool(annotations=WRITE)
def create_project(name: str, key: str, description: str = "", color: str = "#8b5cf6") -> dict[str, Any]:
    """Create a project. Key is a short identifier such as APP or OPS."""
    return _request(
        "POST", "/projects", json={"name": name, "key": key, "description": description, "color": color}
    )


@mcp.tool(annotations=READ)
def list_tasks(
    project_id: str | None = None,
    status: Literal["inbox", "todo", "in_progress", "blocked", "done"] | None = None,
    query: str | None = None,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    """List or search tasks with optional project and status filters."""
    params = {
        key: value
        for key, value in {
            "project_id": project_id,
            "status": status,
            "q": query,
            "include_archived": include_archived,
        }.items()
        if value is not None
    }
    return _request("GET", "/tasks", params=params)


@mcp.tool(annotations=READ)
def get_task(task_id: str) -> dict[str, Any]:
    """Read a task with its checklist, comments and identifier."""
    return _request("GET", f"/tasks/{task_id}")


@mcp.tool(annotations=READ)
def list_task_notes(task_id: str) -> list[dict[str, Any]]:
    """List knowledge notes deliberately connected to a task."""
    return _request("GET", f"/tasks/{task_id}/notes")


@mcp.tool(annotations=WRITE)
def link_task_note(task_id: str, note_id: str) -> None:
    """Connect an existing note to a task so the relationship is usable by people and AI."""
    return _request("POST", f"/tasks/{task_id}/notes/{note_id}")


@mcp.tool(annotations=WRITE)
def unlink_task_note(task_id: str, note_id: str) -> None:
    """Remove only the connection between a task and a note; neither item is deleted."""
    return _request("DELETE", f"/tasks/{task_id}/notes/{note_id}")


@mcp.tool(annotations=WRITE)
def create_task(
    title: str,
    description_markdown: str = "",
    project_id: str | None = None,
    priority: int = 1,
    due_at: str | None = None,
    tags: list[str] | None = None,
    parent_id: str | None = None,
) -> dict[str, Any]:
    """Capture a task. It starts in the inbox unless later updated."""
    return _request(
        "POST",
        "/tasks",
        json={
            "title": title,
            "description_markdown": description_markdown,
            "project_id": project_id,
            "priority": priority,
            "due_at": due_at,
            "tags": tags or [],
            "parent_id": parent_id,
            "source": "mcp",
        },
    )


@mcp.tool(annotations=WRITE)
def update_task(
    task_id: str,
    status: Literal["inbox", "todo", "in_progress", "blocked", "done"] | None = None,
    title: str | None = None,
    description_markdown: str | None = None,
    priority: int | None = None,
    due_at: str | None = None,
) -> dict[str, Any]:
    """Update selected task fields using the current server version."""
    current = get_task(task_id)
    payload: dict[str, Any] = {"base_version": current["version"]}
    payload.update(
        {
            key: value
            for key, value in {
                "status": status,
                "title": title,
                "description_markdown": description_markdown,
                "priority": priority,
                "due_at": due_at,
            }.items()
            if value is not None
        }
    )
    return _request("PATCH", f"/tasks/{task_id}", json=payload)


@mcp.tool(annotations=WRITE)
def add_task_comment(task_id: str, body_markdown: str) -> dict[str, Any]:
    """Add a Markdown comment to a task."""
    return _request(
        "POST", f"/tasks/{task_id}/comments", json={"body_markdown": body_markdown, "source": "mcp"}
    )


@mcp.tool(annotations=WRITE)
def archive_task(task_id: str, archived: bool = True) -> dict[str, Any]:
    """Archive or restore a task. This never permanently deletes it."""
    current = get_task(task_id)
    return _request(
        "PATCH", f"/tasks/{task_id}", json={"base_version": current["version"], "archived": archived}
    )


@mcp.tool(annotations=READ)
def search_notes(query: str, project_id: str | None = None) -> list[dict[str, Any]]:
    """Search indexed Markdown notes."""
    params = {"q": query}
    if project_id:
        params["project_id"] = project_id
    return _request("GET", "/notes", params=params)


@mcp.tool(annotations=READ)
def read_note(note_id: str) -> dict[str, Any]:
    """Read a note with its canonical Markdown and frontmatter."""
    return _request("GET", f"/notes/{note_id}")


@mcp.tool(annotations=READ)
def list_backlinks(note_id: str) -> list[dict[str, Any]]:
    """List notes that link to the selected note."""
    return _request("GET", f"/notes/{note_id}/backlinks")


@mcp.tool(annotations=WRITE)
def write_note(
    title: str,
    content_markdown: str,
    project_id: str | None = None,
    path: str | None = None,
    tags: list[str] | None = None,
    note_id: str | None = None,
) -> dict[str, Any]:
    """Create a Markdown note or update an existing note without deleting history."""
    if note_id:
        current = read_note(note_id)
        return _request(
            "PATCH",
            f"/notes/{note_id}",
            json={
                "base_revision": current["revision"],
                "title": title,
                "path": path or current["path"],
                "project_id": project_id,
                "tags": tags if tags is not None else current["tags"],
                "content_markdown": content_markdown,
                "device_id": "codex-mcp",
            },
        )
    return _request(
        "POST",
        "/notes",
        json={
            "title": title,
            "content_markdown": content_markdown,
            "project_id": project_id,
            "path": path,
            "tags": tags or [],
            "device_id": "codex-mcp",
        },
    )


@mcp.tool(annotations=READ)
def knowledge_graph() -> dict[str, Any]:
    """Return task, note and link graph for visual reasoning or AI context selection."""
    return _request("GET", "/knowledge-graph")


@mcp.tool(annotations=READ)
def daily_brief() -> dict[str, Any]:
    """Return counters, active work and blockers for daily planning."""
    return {
        "summary": _request("GET", "/dashboard"),
        "active": _request("GET", "/tasks", params={"status": "in_progress"}),
        "blocked": _request("GET", "/tasks", params={"status": "blocked"}),
        "inbox": _request("GET", "/tasks", params={"status": "inbox", "limit": 25}),
    }


@mcp.tool(annotations=READ)
def get_project_context(project_id: str) -> dict[str, Any]:
    """Gather a concise project context from tasks and recent indexed notes."""
    projects = list_projects(include_archived=True)
    project = next((item for item in projects if item["id"] == project_id), None)
    if not project:
        raise ValueError("Project not found")
    return {
        "project": project,
        "tasks": list_tasks(project_id=project_id),
        "notes": _request("GET", "/notes", params={"project_id": project_id, "limit": 50}),
    }


def serve() -> None:
    load_config()
    mcp.run()
