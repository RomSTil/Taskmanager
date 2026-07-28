import json
from datetime import UTC, datetime, timedelta

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.event_bus.models import DomainEvent
from app.modules.integrations.max_bot.client import MaxApiClient
from app.modules.integrations.max_bot.models import MaxOutboxMessage
from app.modules.integrations.yandex_direct.client import DirectApiError, YandexDirectClient
from app.modules.integrations.yandex_direct.models import DirectDailyStat, IntegrationJob
from app.modules.integrations.yandex_direct.service import YandexDirectService
from app.modules.integrations.yandex_direct.worker import process_direct_jobs
from app.modules.notifications.service import NotificationService


class FakeDirectClient:
    def get_campaigns(self) -> list[dict]:
        return [
            {
                "Id": 101,
                "Name": "Search",
                "State": "ON",
                "Status": "ACCEPTED",
                "Currency": "RUB",
                "Funds": {
                    "Mode": "CAMPAIGN_FUNDS",
                    "CampaignFunds": {"Balance": 4_500_000_000},
                },
                "Statistics": {"Impressions": 1000, "Clicks": 50},
            }
        ]

    def get_report(self, date_from, date_to, *, campaign_ids=None) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        current = date_from
        while current <= date_to:
            rows.append(
                {
                    "Date": current.isoformat(),
                    "CampaignId": "101",
                    "CampaignName": "Search",
                    "Impressions": "1000",
                    "Clicks": "50",
                    "Cost": "1000.00",
                    "Conversions": "2",
                }
            )
            current += timedelta(days=1)
        return rows


class RegistrationIncompleteDirectClient:
    def get_campaigns(self) -> list[dict]:
        raise DirectApiError(
            58,
            "Yandex Direct API error 58: incomplete application registration",
        )


class SharedAccountDirectClient:
    def get_campaigns(self) -> list[dict]:
        return [
            {
                "Id": 202,
                "Name": "Shared account campaign",
                "State": "ON",
                "Status": "ACCEPTED",
                "Currency": "RUB",
                "Funds": {
                    "Mode": "SHARED_ACCOUNT_FUNDS",
                    "SharedAccountFunds": {"Spend": 1_000_000_000},
                },
                "Statistics": {"Impressions": 1000, "Clicks": 50},
            }
        ]

    def get_report(self, date_from, date_to, *, campaign_ids=None) -> list[dict[str, str]]:
        return [
            {
                "Date": date_from.isoformat(),
                "CampaignId": "202",
                "CampaignName": "Shared account campaign",
                "Impressions": "1000",
                "Clicks": "50",
                "Cost": "1000.00",
                "Conversions": "2",
            }
        ]

    def get_shared_account(self) -> dict | None:
        return None


class SharedAccountWithBalanceDirectClient(SharedAccountDirectClient):
    def get_shared_account(self) -> dict:
        return {
            "Login": "shared-owner",
            "Amount": "2039.87",
            "AmountAvailableForTransfer": "1783.04",
            "Currency": "RUB",
            "AccountID": 118876578,
        }


def test_direct_job_publishes_event_and_queues_max_notification(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    direct_account = client.post(
        "/api/v1/integrations/yandex-direct/accounts",
        headers=auth_headers,
        json={
            "name": "Main Direct",
            "token": "y0_test-token-with-enough-length",
            "balance_threshold": "5000",
            "days_left_threshold": "3",
        },
    )
    assert direct_account.status_code == 201, direct_account.text
    assert direct_account.json()["token_hint"].endswith("length")

    max_bot = client.post(
        "/api/v1/integrations/max/bots",
        headers=auth_headers,
        json={
            "name": "Alerts",
            "token": "max-test-token-with-enough-length",
            "target_type": "user",
            "target_id": 42,
        },
    )
    assert max_bot.status_code == 201, max_bot.text

    account_id = direct_account.json()["id"]
    queued = client.post(
        f"/api/v1/integrations/yandex-direct/accounts/{account_id}/jobs",
        headers=auth_headers,
        json={"job_type": "balance_check"},
    )
    assert queued.status_code == 202, queued.text

    direct = client.app.state.module_context.services.get(YandexDirectService)
    direct.client_factory = lambda _token, _login: FakeDirectClient()
    assert process_direct_jobs(db_session, direct) == 1

    job = db_session.get(IntegrationJob, queued.json()["id"])
    assert job
    db_session.refresh(job)
    assert job.status == "completed"
    assert job.result["balance"] == 4500.0

    event = db_session.scalar(
        select(DomainEvent).where(DomainEvent.event_type == "BudgetRunningLow")
    )
    assert event
    notifications = client.app.state.module_context.services.get(NotificationService)
    assert notifications.dispatch_pending(db_session) == 1

    outbox = db_session.scalar(select(MaxOutboxMessage))
    assert outbox
    assert "Низкий бюджет" in outbox.payload["text"]
    assert outbox.target_id == 42


def test_shared_account_without_balance_does_not_publish_low_budget_event(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    account = client.post(
        "/api/v1/integrations/yandex-direct/accounts",
        headers=auth_headers,
        json={
            "name": "Shared Direct",
            "token": "y0_shared-account-token-with-enough-length",
            "balance_threshold": "5000",
            "days_left_threshold": "3",
        },
    )
    assert account.status_code == 201, account.text
    queued = client.post(
        f"/api/v1/integrations/yandex-direct/accounts/{account.json()['id']}/jobs",
        headers=auth_headers,
        json={"job_type": "balance_check"},
    )
    assert queued.status_code == 202, queued.text

    direct = client.app.state.module_context.services.get(YandexDirectService)
    direct.client_factory = lambda _token, _login: SharedAccountDirectClient()
    assert process_direct_jobs(db_session, direct) == 1

    job = db_session.get(IntegrationJob, queued.json()["id"])
    assert job
    db_session.refresh(job)
    assert job.status == "completed"
    assert job.result["balance"] is None
    assert job.result["days_left"] is None

    event = db_session.scalar(
        select(DomainEvent).where(DomainEvent.event_type == "BudgetRunningLow")
    )
    assert event is None


def test_shared_account_balance_is_loaded_once_and_shown_in_notification(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    account = client.post(
        "/api/v1/integrations/yandex-direct/accounts",
        headers=auth_headers,
        json={
            "name": "Shared Balance",
            "token": "y0_shared-balance-token-with-enough-length",
            "balance_threshold": "1000",
            "days_left_threshold": "3",
        },
    )
    assert account.status_code == 201, account.text
    queued = client.post(
        f"/api/v1/integrations/yandex-direct/accounts/{account.json()['id']}/jobs",
        headers=auth_headers,
        json={"job_type": "balance_check"},
    )
    assert queued.status_code == 202, queued.text

    direct = client.app.state.module_context.services.get(YandexDirectService)
    direct.client_factory = lambda _token, _login: SharedAccountWithBalanceDirectClient()
    assert process_direct_jobs(db_session, direct) == 1

    job = db_session.get(IntegrationJob, queued.json()["id"])
    assert job
    db_session.refresh(job)
    assert job.result["balance"] == 2039.87
    assert job.result["balance_source"] == "shared_account"
    assert job.result["amount_available_for_transfer"] == 1783.04

    notification = direct.balance_notification(db_session)
    assert "2039.87 RUB" in notification.text
    assert "1783.04 RUB" in notification.text


def test_registration_error_fails_direct_job_without_retries(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    account = client.post(
        "/api/v1/integrations/yandex-direct/accounts",
        headers=auth_headers,
        json={
            "name": "Unregistered Direct",
            "token": "y0_unregistered-token-with-enough-length",
        },
    )
    assert account.status_code == 201, account.text
    queued = client.post(
        f"/api/v1/integrations/yandex-direct/accounts/{account.json()['id']}/jobs",
        headers=auth_headers,
        json={"job_type": "balance_check"},
    )
    assert queued.status_code == 202, queued.text

    direct = client.app.state.module_context.services.get(YandexDirectService)
    direct.client_factory = lambda _token, _login: RegistrationIncompleteDirectClient()
    assert process_direct_jobs(db_session, direct) == 0

    job = db_session.get(IntegrationJob, queued.json()["id"])
    assert job
    db_session.refresh(job)
    assert job.status == "failed"
    assert job.attempts == 1
    assert job.executed_at is not None
    assert "error 58" in (job.error or "")
    failed_event = db_session.scalar(
        select(DomainEvent).where(DomainEvent.event_type == "DirectSyncFailed")
    )
    assert failed_event is not None
    assert "error 58" in failed_event.payload["error"]


def test_max_webhook_shows_menu_and_is_idempotent(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    created = client.post(
        "/api/v1/integrations/max/bots",
        headers=auth_headers,
        json={
            "name": "Menu",
            "token": "max-test-token-with-enough-length",
            "allowlist": [42],
        },
    )
    assert created.status_code == 201, created.text
    bot = created.json()
    update = {
        "update_type": "bot_started",
        "timestamp": int(datetime.now(UTC).timestamp() * 1000),
        "user": {"user_id": 42, "name": "Owner"},
    }
    headers = {"X-Max-Bot-Api-Secret": bot["webhook_secret"]}
    url = f"/api/v1/webhooks/max/{bot['id']}"

    assert client.post(url, headers=headers, json=update).status_code == 200
    assert client.post(url, headers=headers, json=update).status_code == 200

    messages = list(db_session.scalars(select(MaxOutboxMessage)))
    assert len(messages) == 1
    assert "Яндекс Директ" in messages[0].payload["text"]
    buttons = messages[0].payload["attachments"][0]["payload"]["buttons"]
    assert buttons[0][0]["payload"] == "direct.overview"
    assert buttons[1][0]["payload"] == "direct.today"
    assert buttons[1][1]["payload"] == "direct.week"
    assert buttons[2][0]["payload"] == "direct.month"
    assert buttons[-1][0]["payload"] == "direct.refresh"
    assert buttons[-1][1]["payload"] == "direct.settings"


def test_max_callback_answers_with_waiting_state_and_returns_metrics(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    monkeypatch,
) -> None:
    created = client.post(
        "/api/v1/integrations/max/bots",
        headers=auth_headers,
        json={
            "name": "Metrics",
            "token": "max-test-token-with-enough-length",
            "allowlist": [42],
        },
    )
    assert created.status_code == 201, created.text
    bot = created.json()
    account = client.post(
        "/api/v1/integrations/yandex-direct/accounts",
        headers=auth_headers,
        json={
            "name": "Metrics Direct",
            "token": "y0_metrics-token-with-enough-length",
        },
    )
    assert account.status_code == 201, account.text
    db_session.add(
        DirectDailyStat(
            account_id=account.json()["id"],
            campaign_id=101,
            campaign_name="Test",
            stat_date=datetime.now(UTC).date(),
            impressions=1000,
            clicks=100,
            cost=500,
            conversions=10,
        )
    )
    db_session.commit()
    answered: dict = {}

    def fake_answer(self, callback_id: str, payload: dict) -> dict:
        answered["callback_id"] = callback_id
        answered["payload"] = payload
        return {"success": True}

    monkeypatch.setattr(MaxApiClient, "answer_callback", fake_answer)
    update = {
        "update_type": "message_callback",
        "timestamp": int(datetime.now(UTC).timestamp() * 1000),
        "callback": {
            "callback_id": "callback-123",
            "payload": "direct.today",
        },
        "user": {"user_id": 42, "name": "Owner"},
    }
    headers = {"X-Max-Bot-Api-Secret": bot["webhook_secret"]}
    response = client.post(
        f"/api/v1/webhooks/max/{bot['id']}",
        headers=headers,
        json=update,
    )
    assert response.status_code == 200, response.text
    assert answered["callback_id"] == "callback-123"
    assert "Пожалуйста, подождите" in answered["payload"]["text"]

    messages = list(db_session.scalars(select(MaxOutboxMessage)))
    assert len(messages) == 1
    assert "CTR: 10.00%" in messages[0].payload["text"]
    assert "Средний CPC: 5.00" in messages[0].payload["text"]
    assert "CPA: 50.00" in messages[0].payload["text"]
    buttons = messages[0].payload["attachments"][0]["payload"]["buttons"]
    assert buttons[0][0]["payload"] == "direct.overview"


def test_max_client_uses_authorization_header_and_user_target() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers["Authorization"]
        captured["query"] = dict(request.url.params)
        return httpx.Response(200, json={"message": {"body": {"text": "ok"}}})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as http_client:
        result = MaxApiClient("secret-token", http_client=http_client).send_message(
            "user",
            42,
            {"text": "hello"},
        )

    assert result["message"]["body"]["text"] == "ok"
    assert captured["authorization"] == "secret-token"
    assert captured["query"] == {"user_id": "42"}


def test_max_client_answers_callback() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["query"] = dict(request.url.params)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"success": True})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as http_client:
        result = MaxApiClient("secret-token", http_client=http_client).answer_callback(
            "callback-123",
            {"text": "waiting"},
        )

    assert result["success"] is True
    assert captured["path"].endswith("/answers")
    assert captured["query"] == {"callback_id": "callback-123"}
    assert captured["body"] == {"message": {"text": "waiting"}}


def test_yandex_client_uses_bearer_token_and_client_login() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers["Authorization"]
        captured["client_login"] = request.headers["Client-Login"]
        captured["path"] = request.url.path
        return httpx.Response(200, json={"result": {"Campaigns": []}})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as http_client:
        campaigns = YandexDirectClient(
            "oauth-token",
            client_login="agency-client",
            http_client=http_client,
        ).get_campaigns()

    assert campaigns == []
    assert captured["authorization"] == "Bearer oauth-token"
    assert captured["client_login"] == "agency-client"
    assert captured["path"].endswith("/json/v5/campaigns")


def test_yandex_client_loads_shared_account_balance_from_live_v4() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "data": {
                    "ActionsResult": [],
                    "Accounts": [
                        {
                            "Login": "shared-owner",
                            "Amount": "2039.87",
                            "AmountAvailableForTransfer": "1783.04",
                            "Currency": "RUB",
                            "AccountID": 118876578,
                        }
                    ],
                }
            },
        )

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as http_client:
        account = YandexDirectClient(
            "oauth-token",
            client_login="shared-owner",
            http_client=http_client,
        ).get_shared_account()

    assert account
    assert account["Amount"] == "2039.87"
    assert captured["path"].endswith("/live/v4/json/")
    assert captured["body"]["method"] == "AccountManagement"
    assert captured["body"]["token"] == "oauth-token"
    assert captured["body"]["param"]["SelectionCriteria"] == {
        "Logins": ["shared-owner"]
    }
