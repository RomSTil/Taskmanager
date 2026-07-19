import uuid

from fastapi.testclient import TestClient


def test_setup_is_single_use_and_login_works(client: TestClient) -> None:
    assert client.get("/api/v1/auth/setup").json() == {"setup_required": True}
    created = client.post(
        "/api/v1/auth/setup", json={"username": "owner", "password": "a-strong-password"}
    )
    assert created.status_code == 201
    assert client.get("/api/v1/auth/setup").json() == {"setup_required": False}
    assert client.post(
        "/api/v1/auth/setup", json={"username": "other", "password": "another-strong-password"}
    ).status_code == 409
    login = client.post(
        "/api/v1/auth/login", json={"username": "owner", "password": "a-strong-password"}
    )
    assert login.status_code == 200
    refresh = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": login.json()["refresh_token"]}
    )
    assert refresh.status_code == 200


def test_project_task_subresources_and_optimistic_conflict(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    project = client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": "Compiler", "key": "CMP", "color": "#22c55e"},
    ).json()
    operation_id = str(uuid.uuid4())
    task_payload = {
        "id": str(uuid.uuid4()),
        "title": "Design IR",
        "project_id": project["id"],
        "priority": 3,
    }
    first = client.post(
        "/api/v1/tasks",
        headers={**auth_headers, "X-Operation-Id": operation_id},
        json=task_payload,
    )
    assert first.status_code == 201, first.text
    task = first.json()
    assert task["identifier"] == "CMP-1"
    duplicate = client.post(
        "/api/v1/tasks",
        headers={**auth_headers, "X-Operation-Id": operation_id},
        json=task_payload,
    )
    assert duplicate.json()["id"] == task["id"]

    checklist = client.post(
        f"/api/v1/tasks/{task['id']}/checklist",
        headers=auth_headers,
        json={"text": "Document invariants"},
    )
    assert checklist.status_code == 201
    comment = client.post(
        f"/api/v1/tasks/{task['id']}/comments",
        headers=auth_headers,
        json={"body_markdown": "Start with **SSA**."},
    )
    assert comment.status_code == 201
    updated = client.patch(
        f"/api/v1/tasks/{task['id']}",
        headers=auth_headers,
        json={"base_version": task["version"], "status": "in_progress"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "in_progress"
    conflict = client.patch(
        f"/api/v1/tasks/{task['id']}",
        headers=auth_headers,
        json={"base_version": task["version"], "priority": 0},
    )
    assert conflict.status_code == 409
    assert client.get("/api/v1/dashboard", headers=auth_headers).json()["in_progress"] == 1


def test_api_token_scopes_block_writes(client: TestClient, auth_headers: dict[str, str]) -> None:
    token = client.post(
        "/api/v1/auth/tokens",
        headers=auth_headers,
        json={"name": "read-only MCP", "scopes": ["projects:read", "tasks:read", "notes:read"]},
    ).json()["token"]
    scoped = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/projects", headers=scoped).status_code == 200
    assert client.post(
        "/api/v1/tasks", headers=scoped, json={"title": "Must fail"}
    ).status_code == 403
