import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OutboxMessage

from app.routers.telegram import _message_kind, _steps_from_text


def test_note_roundtrip_links_and_sync_conflict(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    target = client.post(
        "/api/v1/notes",
        headers=auth_headers,
        json={"title": "Architecture", "path": "Inbox/Architecture.md", "content_markdown": "# Core"},
    )
    assert target.status_code == 201, target.text
    target_note = target.json()
    source = client.post(
        "/api/v1/notes",
        headers=auth_headers,
        json={
            "title": "Daily",
            "path": "Inbox/Daily.md",
            "content_markdown": "See [[Architecture]] and ship it.",
        },
    )
    assert source.status_code == 201
    backlinks = client.get(
        f"/api/v1/notes/{target_note['id']}/backlinks", headers=auth_headers
    ).json()
    assert backlinks[0]["title"] == "Daily"
    assert client.get("/api/v1/notes", headers=auth_headers, params={"q": "ship"}).json()[0]["title"] == "Daily"

    update = client.patch(
        f"/api/v1/notes/{target_note['id']}",
        headers=auth_headers,
        json={"base_revision": 1, "content_markdown": "# Core\nServer edit"},
    )
    assert update.status_code == 200
    sync = client.post(
        "/api/v1/sync/push",
        headers=auth_headers,
        json={
            "operation_id": str(uuid.uuid4()),
            "device_id": "workstation",
            "id": target_note["id"],
            "path": target_note["path"],
            "base_revision": 1,
            "content_markdown": "# Core\nOffline edit",
        },
    )
    assert sync.status_code == 200, sync.text
    assert sync.json()["status"] == "conflict"
    assert ".conflict-workstation-" in sync.json()["conflict"]["path"]


def test_vault_rejects_path_traversal(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/notes",
        headers=auth_headers,
        json={"title": "Escape", "path": "../escape.md", "content_markdown": "no"},
    )
    assert response.status_code == 422
    reserved = client.post(
        "/api/v1/notes",
        headers=auth_headers,
        json={"title": "Internal", "path": ".taskman/config.md", "content_markdown": "no"},
    )
    assert reserved.status_code == 422


def test_note_move_does_not_overwrite_another_vault_file(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    first = client.post(
        "/api/v1/notes",
        headers=auth_headers,
        json={"title": "First", "path": "Inbox/First.md", "content_markdown": "first"},
    ).json()
    second = client.post(
        "/api/v1/notes",
        headers=auth_headers,
        json={"title": "Second", "path": "Inbox/Second.md", "content_markdown": "second"},
    ).json()

    collision = client.patch(
        f"/api/v1/notes/{first['id']}",
        headers=auth_headers,
        json={
            "base_revision": first["revision"],
            "path": second["path"],
            "content_markdown": "overwrite attempt",
        },
    )

    assert collision.status_code == 409
    unchanged = client.get(f"/api/v1/notes/{second['id']}", headers=auth_headers).json()
    assert "second" in unchanged["content_markdown"]
    assert "overwrite attempt" not in unchanged["content_markdown"]


def test_telegram_webhook_allowlist_and_idempotency(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    created = client.post(
        "/api/v1/integrations/telegram/bots",
        headers=auth_headers,
        json={
            "name": "work",
            "token": "123456789:abcdefghijklmnopqrstuvwxyz",
            "allowlist": [42],
        },
    )
    assert created.status_code == 201, created.text
    bot = created.json()
    webhook_headers = {"X-Telegram-Bot-Api-Secret-Token": bot["webhook_secret"]}
    update = {
        "update_id": 100,
        "message": {
            "message_id": 5,
            "chat": {"id": 42},
            "from": {"id": 42, "username": "owner"},
            "text": "Fix <b>production</b> alert",
        },
    }
    url = f"/api/v1/webhooks/telegram/{bot['id']}"
    assert client.post(url, headers=webhook_headers, json=update).status_code == 202
    queued = db_session.scalar(select(OutboxMessage).order_by(OutboxMessage.available_at))
    assert queued
    assert "&lt;b&gt;production&lt;/b&gt;" in queued.payload["text"]
    assert client.post(url, headers=webhook_headers, json=update).status_code == 202
    tasks = client.get("/api/v1/tasks", headers=auth_headers).json()
    assert len(tasks) == 1
    assert tasks[0]["source"] == "telegram"
    denied = {
        **update,
        "update_id": 101,
        "message": {**update["message"], "chat": {"id": 7}, "from": {"id": 7}},
    }
    assert client.post(url, headers=webhook_headers, json=denied).status_code == 202
    assert len(client.get("/api/v1/tasks", headers=auth_headers).json()) == 1


def test_telegram_message_rules_classify_examples() -> None:
    assert _message_kind("+7 985 84 000 84 озон Ксения") == "contact"
    assert _message_kind("Нельзя недовесить нельзя!") == "note"
    assert _message_kind("12 349") == "clarify"
    assert _message_kind("Написать завтра Ксении") == "task"
    assert _message_kind("Подскажите, пожалуйста, как происходит процесс отгрузки?") == "template"
    assert _steps_from_text("Напомнить Лёше взвесить коробку и скинуть Свете") == [
        "Напомнить Лёше",
        "взвесить коробку",
        "скинуть Свете",
    ]
