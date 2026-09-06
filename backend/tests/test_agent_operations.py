import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.models import Task
from app.modules.agent_operations.models import AgentRun
from app.models import OutboxMessage, TelegramAgentSubscription
from app.modules.integrations.max_bot.models import MaxOutboxMessage
from app.modules.notifications.service import NotificationService


def _task(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post("/api/v1/tasks", headers=headers, json={"title": "Исследовать ведра"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _runner(client: TestClient, headers: dict[str, str]) -> tuple[str, dict[str, str]]:
    response = client.post(
        "/api/v1/agent-runners/register",
        headers=headers,
        json={"name": "Owner PC", "version": "0.1.0", "capabilities": ["browser", "codex"]},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["id"], {"X-Taskman-Runner-Token": body["runner_token"]}


def test_scoped_api_token_can_register_runner(client: TestClient, auth_headers: dict[str, str]) -> None:
    token = client.post(
        "/api/v1/auth/tokens",
        headers=auth_headers,
        json={"name": "Codex Runner", "scopes": ["agent_operations:write"]},
    ).json()["token"]

    response = client.post(
        "/api/v1/agent-runners/register",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Scoped runner", "version": "0.1.0", "capabilities": ["codex"]},
    )

    assert response.status_code == 201, response.text


def test_agent_run_requires_owner_review_and_approval(client: TestClient, auth_headers: dict[str, str], db_session) -> None:
    task_id = _task(client, auth_headers)
    created = client.post(
        "/api/v1/agent-runs",
        headers=auth_headers,
        json={"task_id": task_id, "goal": "Найти пищевые ведра 1, 5 и 10 кг", "mode": "analysis", "allowed_actions": ["research", "browser"]},
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    assert created.json()["status"] == "queued"

    runner_id, runner_headers = _runner(client, auth_headers)
    runners = client.get("/api/v1/agent-runners", headers=auth_headers)
    assert runners.status_code == 200, runners.text
    assert runners.json()[0]["id"] == runner_id
    assert runners.json()[0]["online"] is True
    claimed = client.post(f"/api/v1/agent-runners/{runner_id}/claim", headers=runner_headers)
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["run"]["id"] == run_id
    assert claimed.json()["assignment_token"]
    run = db_session.get(AgentRun, run_id)
    assert run is not None
    run.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
    db_session.commit()
    payload = {
        "run_id": run_id,
        "runner_id": runner_id,
        "role": "coordinator",
        "lease": int(datetime.now(UTC).timestamp()) - 1,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    signature = hmac.new(
        get_settings().effective_jwt_secret.encode("utf-8"), encoded.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    assignment_headers = runner_headers | {"X-Taskman-Assignment": f"{encoded}.{signature}"}

    progress = client.post(
        f"/api/v1/agent-runs/{run_id}/events",
        headers=assignment_headers,
        json={"event_type": "progress", "summary": "Ищу поставщиков"},
    )
    assert progress.status_code == 201, progress.text
    approval_event = client.post(
        f"/api/v1/agent-runs/{run_id}/events",
        headers=assignment_headers,
        json={
            "event_type": "approval_requested",
            "summary": "Готово письмо поставщику",
            "payload": {
                "action": "external_message",
                "explanation": "Отправить подготовленное письмо поставщику.",
                "idempotency_key": f"{run_id}:supplier-email:1",
                "details": {"domain": "example.test"},
            },
        },
    )
    assert approval_event.status_code == 201, approval_event.text
    current = client.get(f"/api/v1/agent-runs/{run_id}", headers=auth_headers)
    assert current.json()["status"] == "waiting_approval"
    approval_id = current.json()["approvals"][0]["id"]

    decision = client.post(
        f"/api/v1/agent-runs/{run_id}/approvals/{approval_id}/decision",
        headers=auth_headers,
        json={"decision": "approved"},
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["status"] == "queued"

    claimed_again = client.post(f"/api/v1/agent-runners/{runner_id}/claim", headers=runner_headers)
    assert claimed_again.status_code == 200, claimed_again.text
    assignment_headers = runner_headers | {"X-Taskman-Assignment": claimed_again.json()["assignment_token"]}
    completed = client.post(
        f"/api/v1/agent-runs/{run_id}/complete",
        headers=assignment_headers,
        json={"outcome": "owner_review", "summary": "Есть рекомендованный поставщик."},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "waiting_owner_review"

    feedback = client.post(
        f"/api/v1/agent-runs/{run_id}/feedback",
        headers=auth_headers,
        json={"message": "Добавь MOQ", "labels": ["logic"]},
    )
    assert feedback.status_code == 200, feedback.text
    assert feedback.json()["status"] == "queued"
    assert len(feedback.json()["steps"]) == 2


def test_runner_can_observe_a_cancelled_assignment(client: TestClient, auth_headers: dict[str, str]) -> None:
    task_id = _task(client, auth_headers)
    run = client.post(
        "/api/v1/agent-runs",
        headers=auth_headers,
        json={"task_id": task_id, "goal": "Проверить отмену"},
    ).json()
    runner_id, runner_headers = _runner(client, auth_headers)
    claimed = client.post(f"/api/v1/agent-runners/{runner_id}/claim", headers=runner_headers)
    assert claimed.status_code == 200, claimed.text
    cancelled = client.post(f"/api/v1/agent-runs/{run['id']}/cancel", headers=auth_headers)
    assert cancelled.status_code == 200, cancelled.text
    control = client.get(f"/api/v1/agent-runners/{runner_id}/control", headers=runner_headers)
    assert control.status_code == 200, control.text
    assert control.json()["cancelled_run_ids"] == [run["id"]]


def test_research_run_routes_to_market_researcher_and_records_usage(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    task_id = _task(client, auth_headers)
    run = client.post(
        "/api/v1/agent-runs",
        headers=auth_headers,
        json={"task_id": task_id, "goal": "Найти поставщиков", "allowed_actions": ["research", "browser"]},
    ).json()
    runner_id, runner_headers = _runner(client, auth_headers)
    assignment = client.post(f"/api/v1/agent-runners/{runner_id}/claim", headers=runner_headers).json()
    headers = runner_headers | {"X-Taskman-Assignment": assignment["assignment_token"]}
    progress = client.post(
        f"/api/v1/agent-runs/{run['id']}/events",
        headers=headers,
        json={
            "event_type": "progress",
            "summary": "Выбрана модель.",
            "payload": {"model": "gpt-6-astra", "effort": "automatic", "input_tokens": 120, "output_tokens": 33},
        },
    )
    assert progress.status_code == 201, progress.text
    handoff = client.post(
        f"/api/v1/agent-runs/{run['id']}/events",
        headers=headers,
        json={"event_type": "role_completed", "summary": "Передаю исследователю.", "payload": {"next_role": "market_researcher"}},
    )
    assert handoff.status_code == 201, handoff.text
    current = client.get(f"/api/v1/agent-runs/{run['id']}", headers=auth_headers).json()
    assert current["role"] == "market_researcher"
    assert current["selected_model"] == "gpt-6-astra"
    assert current["usage_input_tokens"] == 120
    assert current["usage_output_tokens"] == 33


def test_telegram_start_subscribes_chat_to_safe_agent_trace(
    client: TestClient, auth_headers: dict[str, str], db_session
) -> None:
    bot = client.post(
        "/api/v1/integrations/telegram/bots",
        headers=auth_headers,
        json={"name": "Agent trace", "token": "123456789:abcdefghijklmnopqrstuvwxyz", "allowlist": [42]},
    ).json()
    update = {
        "update_id": 321,
        "message": {"message_id": 1, "chat": {"id": 42}, "from": {"id": 42}, "text": "/start"},
    }
    response = client.post(
        f"/api/v1/webhooks/telegram/{bot['id']}",
        headers={"X-Telegram-Bot-Api-Secret-Token": bot["webhook_secret"]},
        json=update,
    )
    assert response.status_code == 202, response.text
    assert db_session.scalar(select(TelegramAgentSubscription)) is not None
    task_id = _task(client, auth_headers)
    client.post("/api/v1/agent-runs", headers=auth_headers, json={"task_id": task_id, "goal": "Проверить trace"})
    texts = [message.payload["text"] for message in db_session.scalars(select(OutboxMessage))]
    assert any("IT-отдел" in text for text in texts)


def test_max_operations_bot_turns_a_free_text_goal_into_an_agent_run(
    client: TestClient, auth_headers: dict[str, str], db_session
) -> None:
    created = client.post(
        "/api/v1/integrations/max/bots",
        headers=auth_headers,
        json={
            "name": "Operations",
            "token": "max-operations-token-with-enough-length",
            "integration": "operations",
            "target_type": "user",
            "target_id": 42,
        },
    )
    assert created.status_code == 201, created.text
    bot = created.json()
    headers = {"X-Max-Bot-Api-Secret": bot["webhook_secret"]}
    url = f"/api/v1/webhooks/max/{bot['id']}"
    started = {
        "update_type": "bot_started",
        "user": {"user_id": 42, "name": "Owner"},
    }
    assert client.post(url, headers=headers, json=started).status_code == 200
    assert "Работа Codex" in db_session.scalar(select(MaxOutboxMessage)).payload["text"]

    goal = {
        "update_type": "message_created",
        "message": {"sender": {"user_id": 42, "name": "Owner"}, "recipient": {"user_id": 42}, "body": {"text": "Найди ведра для чеснока"}},
    }
    response = client.post(url, headers=headers, json=goal)
    assert response.status_code == 200, response.text
    task = db_session.scalar(select(Task).where(Task.source == "max"))
    assert task is not None
    run = db_session.scalar(select(AgentRun).where(AgentRun.task_id == task.id))
    assert run is not None
    assert run.goal == "Найди ведра для чеснока"


def test_agent_status_notification_reaches_only_operations_max_bots(
    client: TestClient, auth_headers: dict[str, str], db_session
) -> None:
    bot = client.post(
        "/api/v1/integrations/max/bots",
        headers=auth_headers,
        json={
            "name": "Operations alerts",
            "token": "max-operations-alert-token-with-enough-length",
            "integration": "operations",
            "target_type": "user",
            "target_id": 42,
        },
    )
    assert bot.status_code == 201, bot.text
    task_id = _task(client, auth_headers)
    run = client.post(
        "/api/v1/agent-runs",
        headers=auth_headers,
        json={"task_id": task_id, "goal": "Проверить оповещение"},
    )
    assert run.status_code == 201, run.text
    notifications = client.app.state.module_context.services.get(NotificationService)
    assert notifications.dispatch_pending(db_session) == 1
    outbox = db_session.scalar(select(MaxOutboxMessage))
    assert outbox is not None
    buttons = outbox.payload["attachments"][0]["payload"]["buttons"]
    assert buttons[0][0]["payload"] == "operations.active"
