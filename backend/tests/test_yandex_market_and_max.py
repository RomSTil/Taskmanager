from datetime import UTC, datetime

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.integrations.max_bot.models import MaxAccessRequest, MaxOutboxMessage
from app.modules.integrations.yandex_market.client import YandexMarketClient
from app.modules.integrations.yandex_market.models import MarketOrder
from app.modules.integrations.yandex_market.service import YandexMarketService
from app.modules.integrations.yandex_market.worker import process_market_pack_requests


class FakeMarketClient:
    def __init__(self) -> None:
        self.ready_order_ids: list[int] = []

    def get_processing_orders(self) -> list[dict]:
        return [
            {
                "id": 9001,
                "status": "PROCESSING",
                "substatus": "STARTED",
                "creationDate": "21-08-2026 11:18:00",
                "items": [
                    {"offerId": "sku-1", "offerName": "Чехол для инструмента", "count": 2}
                ],
            }
        ]

    def mark_ready_to_ship(self, order_id: int) -> dict:
        self.ready_order_ids.append(order_id)
        return {
            "status": "OK",
            "result": {
                "order": {
                    "id": order_id,
                    "status": "PROCESSING",
                    "substatus": "READY_TO_SHIP",
                }
            },
        }


def test_market_client_uses_api_key_and_ready_to_ship_contract() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "orders": [
                        {
                            "id": 9001,
                            "status": "PROCESSING",
                            "substatus": "STARTED",
                            "items": [],
                        }
                    ],
                    "paging": {},
                },
            )
        return httpx.Response(200, json={"status": "OK", "result": {}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        market = YandexMarketClient("market-api-key", 12345, http_client=http_client)
        assert market.get_processing_orders()[0]["id"] == 9001
        market.mark_ready_to_ship(9001)

    assert requests[0].headers["Api-Key"] == "market-api-key"
    assert requests[0].url.path == "/v2/campaigns/12345/orders"
    assert requests[0].url.params.get_list("status") == ["PROCESSING"]
    assert requests[0].url.params.get_list("substatus") == ["STARTED"]
    assert requests[1].method == "PUT"
    assert requests[1].url.path == "/v2/campaigns/12345/orders/9001/status"
    assert requests[1].read().decode() == (
        '{"order":{"status":"PROCESSING","substatus":"READY_TO_SHIP"}}'
    )


def test_market_bot_registration_roles_notification_and_pack_flow(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    account_response = client.post(
        "/api/v1/integrations/yandex-market/accounts",
        headers=auth_headers,
        json={
            "name": "Основной магазин",
            "campaign_id": 12345,
            "api_key": "market-api-key-with-enough-length",
            "poll_interval_seconds": 60,
        },
    )
    assert account_response.status_code == 201, account_response.text
    account = account_response.json()
    bot_response = client.post(
        "/api/v1/integrations/max/bots",
        headers=auth_headers,
        json={
            "name": "Market packing",
            "token": "max-market-token-with-enough-length",
            "integration": "market",
            "target_type": "user",
            "target_id": 42,
        },
    )
    assert bot_response.status_code == 201, bot_response.text
    bot = bot_response.json()
    webhook_headers = {"X-Max-Bot-Api-Secret": bot["webhook_secret"]}
    webhook_url = f"/api/v1/webhooks/max/{bot['id']}"
    timestamp = int(datetime.now(UTC).timestamp() * 1000)

    assert client.post(
        webhook_url,
        headers=webhook_headers,
        json={
            "update_type": "message_created",
            "timestamp": timestamp,
            "message": {
                "sender": {"user_id": 77, "name": "Сборщик Анна"},
                "recipient": {"user_id": 77},
                "body": {"text": "/start"},
            },
        },
    ).status_code == 200
    access = db_session.scalar(
        select(MaxAccessRequest).where(MaxAccessRequest.user_id == 77)
    )
    assert access
    access_response = client.get(
        f"/api/v1/integrations/max/bots/{bot['id']}/access-requests",
        headers=auth_headers,
    )
    assert access_response.status_code == 200, access_response.text
    assert access_response.json()[0]["display_name"] == "Сборщик Анна"
    role_response = client.patch(
        f"/api/v1/integrations/max/bots/{bot['id']}/access-requests/{access.id}",
        headers=auth_headers,
        json={"status": "approved", "role": "picker"},
    )
    assert role_response.status_code == 200, role_response.text
    assert role_response.json()["role"] == "picker"
    moderation = next(
        message
        for message in db_session.scalars(select(MaxOutboxMessage))
        if "Какую роль" in message.payload["text"]
    )
    buttons = moderation.payload["attachments"][0]["payload"]["buttons"][0]
    assert [button["payload"] for button in buttons] == [
        f"max.access.approve_picker:{access.id}",
        f"max.access.approve_admin:{access.id}",
        f"max.access.deny:{access.id}",
    ]

    assert client.post(
        webhook_url,
        headers=webhook_headers,
        json={
            "update_type": "message_callback",
            "timestamp": timestamp + 1,
            "callback": {
                "callback_id": "approve-picker",
                "payload": f"max.access.approve_picker:{access.id}",
            },
            "user": {"user_id": 42, "name": "Владелец"},
        },
    ).status_code == 200
    db_session.refresh(access)
    assert access.status == "approved"
    assert access.role == "picker"

    fake_market = FakeMarketClient()
    service = client.app.state.module_context.services.get(YandexMarketService)
    service.client_factory = lambda _api_key, _campaign_id: fake_market
    sync_response = client.post(
        f"/api/v1/integrations/yandex-market/accounts/{account['id']}/sync",
        headers=auth_headers,
    )
    assert sync_response.status_code == 202, sync_response.text
    assert sync_response.json() == {"new_orders": 1}
    order = db_session.scalar(select(MarketOrder).where(MarketOrder.market_order_id == 9001))
    assert order
    notifications = list(
        db_session.scalars(
            select(MaxOutboxMessage).where(
                MaxOutboxMessage.payload["text"]
                .as_string()
                .contains("Яндекс Маркет — новый заказ №9001")
            )
        )
    )
    assert {message.target_id for message in notifications} == {42, 77}
    picker_message = next(message for message in notifications if message.target_id == 77)
    assert "📅 Дата заказа: **21.08.2026**" in picker_message.payload["text"]
    assert "🔢 Количество штук: **2**" in picker_message.payload["text"]
    pack_action = picker_message.payload["attachments"][0]["payload"]["buttons"][0][0][
        "payload"
    ]
    assert pack_action == f"market.pack:{order.id}"

    assert client.post(
        webhook_url,
        headers=webhook_headers,
        json={
            "update_type": "message_callback",
            "timestamp": timestamp + 2,
            "callback": {"callback_id": "pack-order", "payload": pack_action},
            "user": {"user_id": 77, "name": "Сборщик Анна"},
        },
    ).status_code == 200
    db_session.refresh(order)
    assert order.pack_state == "pending"
    assert order.pack_requested_by == 77

    assert process_market_pack_requests(db_session, service) == 1
    db_session.refresh(order)
    assert order.pack_state == "packed"
    assert order.substatus == "READY_TO_SHIP"
    assert fake_market.ready_order_ids == [9001]
    messages = list(db_session.scalars(select(MaxOutboxMessage)))
    assert any(
        message.target_id == 42
        and "Сборщик: Сборщик Анна" in message.payload["text"]
        for message in messages
    )
