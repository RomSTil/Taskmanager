from datetime import UTC, date, datetime

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.event_bus.models import DomainEvent
from app.modules.integrations.max_bot.formatter import menu_payload
from app.modules.integrations.max_bot.models import MaxOutboxMessage
from app.modules.integrations.ozon_seller.client import OzonSellerClient
from app.modules.integrations.ozon_seller.models import OzonPosting, OzonSellerAccount
from app.modules.integrations.ozon_seller.service import OzonSellerService
from app.modules.integrations.yandex_market.models import MarketOrder, YandexMarketAccount
from app.modules.integrations.yandex_market.service import YandexMarketService
from app.modules.notifications.service import InteractionRegistry, NotificationService
from app.security import encrypt_secret


def posting(number: str, name: str = "Чеснок посадочный") -> dict:
    return {
        "posting_number": number,
        "order_number": number.rsplit("-", 1)[0],
        "status": "awaiting_packaging",
        "created_at": "2026-08-19T10:00:00Z",
        "shipment_date": "2026-08-20T12:00:00Z",
        "products": [
            {
                "name": name,
                "offer_id": "GARLIC-1",
                "sku": 123,
                "quantity": 2,
                "price": "750.50",
                "currency_code": "RUB",
            }
        ],
    }


class FakeOzonClient:
    def __init__(self) -> None:
        self.fbs = [posting("10001-0001-1")]
        self.fbo: list[dict] = []

    def list_fbs_postings(self, _since, _to) -> list[dict]:
        return self.fbs

    def list_fbo_postings(self, _since, _to) -> list[dict]:
        return self.fbo


def test_ozon_new_order_is_sent_to_max_once(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    account_response = client.post(
        "/api/v1/integrations/ozon/accounts",
        headers=auth_headers,
        json={
            "name": "Main Ozon",
            "client_id": "123456",
            "api_key": "ozon-api-key-with-enough-length",
            "poll_interval_minutes": 5,
        },
    )
    assert account_response.status_code == 201, account_response.text
    assert account_response.json()["api_key_hint"].endswith("length")
    bot_response = client.post(
        "/api/v1/integrations/max/bots",
        headers=auth_headers,
        json={
            "name": "Ozon alerts",
            "token": "max-token-with-enough-length",
            "integration": "market",
            "target_type": "user",
            "target_id": 42,
        },
    )
    assert bot_response.status_code == 201, bot_response.text
    interactions = client.app.state.module_context.services.get(InteractionRegistry)
    buttons = menu_payload(interactions, "market")["attachments"][0]["payload"]["buttons"]
    actions = {button["payload"] for row in buttons for button in row}
    assert "market.ozon_orders" in actions
    assert "market.ozon_refresh" in actions
    assert "market.shipment_plan" in actions

    service = client.app.state.module_context.services.get(OzonSellerService)
    fake = FakeOzonClient()
    service.client_factory = lambda _client_id, _api_key: fake
    account = db_session.get(OzonSellerAccount, account_response.json()["id"])
    assert account

    baseline = service.sync_account(db_session, account)
    assert baseline == {
        "account_id": account.id,
        "fetched": 1,
        "created": 1,
        "notified": 0,
        "baseline": True,
    }
    assert db_session.scalar(select(func.count()).select_from(DomainEvent)) == 0

    fake.fbs.append(posting("10002-0002-1", "Чеснок товарный"))
    fake.fbs[-1]["created_at"] = datetime.now(UTC).isoformat()
    result = service.sync_account(db_session, account, now=datetime.now(UTC))
    assert result["created"] == 1
    assert result["notified"] == 1
    event = db_session.scalar(
        select(DomainEvent).where(DomainEvent.event_type == "OzonOrderCreated")
    )
    assert event
    assert event.payload["posting_number"] == "10002-0002-1"
    assert event.payload["total"] == 1501.0

    notifications = client.app.state.module_context.services.get(NotificationService)
    assert notifications.dispatch_pending(db_session) == 1
    outbox = db_session.scalar(select(MaxOutboxMessage))
    assert outbox
    text = outbox.payload["text"]
    assert "🔵 **Ozon — новый заказ №10002-0002-1**" in text
    assert "📅 Дата заказа: **21.08.2026**" in text
    assert "🔢 Количество штук: **2**" in text
    assert "• Чеснок товарный × 2" in text
    assert "📌 Статус: `awaiting_packaging`" in text
    assert "💰 Сумма: **1501.00 RUB**" in text
    assert "⏰ Отгрузить до: **20.08.2026, 15:00 (МСК)**" in text
    assert outbox.target_id == 42

    recent = service.recent_orders_notification(db_session).text
    assert "🔵 **Ozon — заказ №10002-0002-1**" in recent
    assert "📅 Дата заказа: **21.08.2026**" in recent
    assert "🔢 Количество штук: **2**" in recent
    assert "• Чеснок товарный × 2" in recent
    assert "⏰ Отгрузить до: **20.08.2026, 15:00 (МСК)**" in recent
    assert "🚚 Схема: **FBS** · 💰 **1501.00 RUB**" in recent

    repeated = service.sync_account(db_session, account, now=datetime.now(UTC))
    assert repeated["created"] == 0
    assert repeated["notified"] == 0
    assert db_session.scalar(select(func.count()).select_from(OzonPosting)) == 2
    assert db_session.scalar(select(func.count()).select_from(DomainEvent)) == 1

    fake.fbs.append(posting("10003-0003-1", "Старый заказ"))
    historical = service.sync_account(db_session, account, now=datetime.now(UTC))
    assert historical["created"] == 1
    assert historical["notified"] == 0
    assert db_session.scalar(select(func.count()).select_from(DomainEvent)) == 1

    fake.fbs[0]["status"] = "delivered"
    service.sync_account(db_session, account, now=datetime.now(UTC))
    stored = db_session.scalar(
        select(OzonPosting).where(OzonPosting.posting_number == "10001-0001-1")
    )
    assert stored and stored.status == "delivered"


def test_shipment_plan_aggregates_actionable_marketplace_orders(
    client: TestClient,
    db_session: Session,
) -> None:
    market_account = YandexMarketAccount(
        name="Market cabinet",
        campaign_id=12345,
        api_key_encrypted=encrypt_secret("market-api-key-with-enough-length"),
        api_key_hint="...length",
    )
    ozon_account = OzonSellerAccount(
        name="Ozon cabinet",
        client_id="123456",
        api_key_encrypted=encrypt_secret("ozon-api-key-with-enough-length"),
        api_key_hint="...length",
    )
    db_session.add_all([market_account, ozon_account])
    db_session.flush()
    db_session.add_all(
        [
            MarketOrder(
                account_id=market_account.id,
                market_order_id=1001,
                status="PROCESSING",
                substatus="STARTED",
                items=[{"offerName": "Чеснок Любаша", "count": 2}],
                shipment_date=date(2026, 8, 21),
            ),
            MarketOrder(
                account_id=market_account.id,
                market_order_id=1002,
                status="PROCESSING",
                substatus="READY_TO_SHIP",
                items=[{"offerName": "Чеснок Любаша", "count": 1}],
                shipment_date=date(2026, 8, 22),
            ),
            MarketOrder(
                account_id=market_account.id,
                market_order_id=1003,
                status="DELIVERY",
                substatus="DELIVERY_SERVICE_RECEIVED",
                items=[{"offerName": "Не учитывать", "count": 10}],
            ),
            OzonPosting(
                account_id=ozon_account.id,
                scheme="FBS",
                posting_number="2001-1",
                status="awaiting_packaging",
                products=[{"name": "Чеснок Любаша", "quantity": 3}],
                shipment_date=datetime(2026, 8, 22, 7, tzinfo=UTC),
            ),
            OzonPosting(
                account_id=ozon_account.id,
                scheme="FBS",
                posting_number="2002-1",
                status="awaiting_deliver",
                products=[{"name": "Чеснок Добрыня", "quantity": 2}],
                shipment_date=datetime(2026, 8, 23, 7, tzinfo=UTC),
            ),
            OzonPosting(
                account_id=ozon_account.id,
                scheme="FBO",
                posting_number="2003-1",
                status="awaiting_deliver",
                products=[{"name": "Не учитывать", "quantity": 20}],
            ),
        ]
    )
    db_session.commit()

    service = client.app.state.module_context.services.get(YandexMarketService)
    text = service.shipment_plan_notification(
        db_session,
        now=datetime(2026, 8, 21, 12, tzinfo=UTC),
    ).text

    assert "Сегодня и просрочено · 21.08" in text
    assert "Посылок: **1** · товаров: **2 шт.**" in text
    assert "Завтра · 22.08" in text
    assert "Посылок: **2** · товаров: **4 шт.**" in text
    assert "Позже" in text
    assert "Чеснок Добрыня — **2 шт.**" in text
    assert "Не учитывать" not in text


def test_ozon_client_sends_credentials_and_paginates() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        offset = request.read().decode("utf-8")
        has_next = '"offset":0' in offset
        return httpx.Response(
            200,
            json={
                "result": {
                    "postings": [posting("20001-0001-1")],
                    "has_next": has_next,
                }
            },
        )

    with httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://api-seller.ozon.ru",
    ) as http_client:
        api = OzonSellerClient("client-123", "secret-key", http_client=http_client)
        result = api.list_fbs_postings(
            datetime(2026, 8, 18, tzinfo=UTC),
            datetime(2026, 8, 19, tzinfo=UTC),
        )

    assert len(result) == 2
    assert len(requests) == 2
    assert requests[0].headers["Client-Id"] == "client-123"
    assert requests[0].headers["Api-Key"] == "secret-key"
    assert requests[0].url.path == "/v3/posting/fbs/list"
