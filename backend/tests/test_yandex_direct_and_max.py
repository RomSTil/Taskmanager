from datetime import UTC, datetime, timedelta

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.event_bus.models import DomainEvent
from app.modules.integrations.max_bot.client import MaxApiClient
from app.modules.integrations.max_bot.models import MaxOutboxMessage
from app.modules.integrations.yandex_direct.client import DirectApiError, YandexDirectClient
from app.modules.integrations.yandex_direct.models import IntegrationJob
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
    assert messages[0].payload["text"] == "Яндекс Директ"
    buttons = messages[0].payload["attachments"][0]["payload"]["buttons"]
    assert buttons[0][0]["payload"] == "direct.balance"
    assert buttons[-1][0]["payload"] == "direct.settings"


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
