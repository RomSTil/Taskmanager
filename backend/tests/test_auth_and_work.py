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


def test_workspace_bootstrap_returns_initial_client_state(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    assert client.get("/api/v1/bootstrap").status_code == 401

    response = client.get("/api/v1/bootstrap", headers=auth_headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["user"]["username"] == "owner"
    assert [user["username"] for user in payload["users"]] == ["owner"]
    assert [project["key"] for project in payload["projects"]] == ["HOME"]
    assert payload["tasks"] == []
    assert payload["views"] == []
    assert payload["dashboard"] == {
        "inbox": 0,
        "todo": 0,
        "in_progress": 0,
        "blocked": 0,
        "done": 0,
        "overdue": 0,
    }
    assert payload["server_time"]


def test_task_creator_and_assignee_are_recorded(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    bootstrap = client.get("/api/v1/bootstrap", headers=auth_headers).json()
    owner = bootstrap["user"]
    project = bootstrap["projects"][0]

    response = client.post(
        "/api/v1/tasks",
        headers=auth_headers,
        json={
            "title": "Prepare release",
            "project_id": project["id"],
            "due_at": "2026-10-31T23:59:00Z",
            "source_data": {
                "deadline_start": "2026-10-20T00:00:00Z",
                "assignee_user_id": owner["id"],
            },
        },
    )

    assert response.status_code == 201, response.text
    source_data = response.json()["source_data"]
    assert source_data["created_by_user_id"] == owner["id"]
    assert source_data["created_by_username"] == "owner"
    assert source_data["assignee_user_id"] == owner["id"]
    assert source_data["assignee_username"] == "owner"


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


def test_task_hierarchy_rejects_cycles(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    project = client.get("/api/v1/projects", headers=auth_headers).json()[0]
    parent = client.post(
        "/api/v1/tasks",
        headers=auth_headers,
        json={"title": "Parent", "project_id": project["id"]},
    ).json()
    child = client.post(
        "/api/v1/tasks",
        headers=auth_headers,
        json={
            "title": "Child",
            "project_id": project["id"],
            "parent_id": parent["id"],
        },
    ).json()

    response = client.patch(
        f"/api/v1/tasks/{parent['id']}",
        headers=auth_headers,
        json={"base_version": parent["version"], "parent_id": child["id"]},
    )

    assert response.status_code == 422
    assert "cycle" in response.json()["detail"].lower()
