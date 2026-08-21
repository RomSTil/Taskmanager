import logging
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ....security import decrypt_secret, encrypt_secret
from ...notifications.service import Notification
from ..max_bot.models import MaxAccessRequest, MaxBotConfig, MaxOutboxMessage
from .client import YandexMarketClient
from .formatter import (
    new_order_payload,
    orders_payload,
    pack_failed_payload,
    pack_queued_payload,
    packed_payload,
)
from .models import MarketOrder, YandexMarketAccount
from .schemas import MarketAccountCreate, MarketAccountUpdate

ClientFactory = Callable[[str, int], YandexMarketClient]
MARKET_TIMEZONE = ZoneInfo("Europe/Moscow")
logger = logging.getLogger(__name__)


def _parse_market_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.strptime(text, "%d-%m-%Y %H:%M:%S").replace(
                tzinfo=MARKET_TIMEZONE
            )
        except ValueError:
            try:
                parsed = datetime.fromisoformat(text)
            except ValueError:
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=MARKET_TIMEZONE)
    return parsed.astimezone(UTC)


def _parse_shipment_date(remote: dict) -> date | None:
    delivery = remote.get("delivery")
    if not isinstance(delivery, dict):
        return None
    dates: list[date] = []
    for shipment in delivery.get("shipments") or []:
        if not isinstance(shipment, dict):
            continue
        value = str(shipment.get("shipmentDate") or "").strip()
        if not value:
            continue
        try:
            dates.append(datetime.strptime(value, "%d-%m-%Y").date())
        except ValueError:
            try:
                dates.append(date.fromisoformat(value))
            except ValueError:
                continue
    return min(dates) if dates else None


class YandexMarketService:
    def __init__(self, *, client_factory: ClientFactory | None = None) -> None:
        self.client_factory = client_factory or (
            lambda api_key, campaign_id: YandexMarketClient(api_key, campaign_id)
        )

    def account(self, session: Session, account_id: str) -> YandexMarketAccount:
        account = session.get(YandexMarketAccount, account_id)
        if account is None:
            raise LookupError("Yandex Market account not found")
        return account

    def create_account(
        self, session: Session, payload: MarketAccountCreate
    ) -> YandexMarketAccount:
        account = YandexMarketAccount(
            name=payload.name,
            campaign_id=payload.campaign_id,
            api_key_encrypted=encrypt_secret(payload.api_key),
            api_key_hint=f"…{payload.api_key[-6:]}",
            enabled=payload.enabled,
            poll_interval_seconds=payload.poll_interval_seconds,
        )
        session.add(account)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise ValueError("Yandex Market account already exists") from exc
        session.refresh(account)
        return account

    def update_account(
        self,
        session: Session,
        account_id: str,
        payload: MarketAccountUpdate,
    ) -> YandexMarketAccount:
        account = self.account(session, account_id)
        if account.version != payload.base_version:
            raise RuntimeError("Yandex Market account version conflict")
        for field in ("name", "campaign_id", "enabled", "poll_interval_seconds"):
            if field in payload.model_fields_set:
                setattr(account, field, getattr(payload, field))
        if payload.api_key:
            account.api_key_encrypted = encrypt_secret(payload.api_key)
            account.api_key_hint = f"…{payload.api_key[-6:]}"
        account.version += 1
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise ValueError("Yandex Market account already exists") from exc
        session.refresh(account)
        return account

    def _recipients(
        self, session: Session, bot: MaxBotConfig
    ) -> list[tuple[str, int, str]]:
        recipients: dict[tuple[str, int], str] = {}
        if bot.target_type and bot.target_id is not None:
            recipients[(bot.target_type, int(bot.target_id))] = "admin"
        for access in session.scalars(
            select(MaxAccessRequest).where(
                MaxAccessRequest.bot_id == bot.id,
                MaxAccessRequest.status == "approved",
            )
        ):
            recipients[(access.target_type, access.target_id)] = access.role
        return [
            (target_type, target_id, role)
            for (target_type, target_id), role in recipients.items()
        ]

    def _market_bots(self, session: Session) -> list[MaxBotConfig]:
        return list(
            session.scalars(
                select(MaxBotConfig).where(
                    MaxBotConfig.enabled.is_(True),
                    MaxBotConfig.integration == "market",
                )
            )
        )

    def _queue_new_order(self, session: Session, order: MarketOrder) -> None:
        for bot in self._market_bots(session):
            for target_type, target_id, role in self._recipients(session, bot):
                session.add(
                    MaxOutboxMessage(
                        bot_id=bot.id,
                        target_type=target_type,
                        target_id=target_id,
                        payload=new_order_payload(order, picker=role == "picker"),
                    )
                )

    def sync_account(self, session: Session, account: YandexMarketAccount) -> int:
        client = self.client_factory(
            decrypt_secret(account.api_key_encrypted), account.campaign_id
        )
        now = datetime.now(UTC)
        created = 0
        for remote in client.get_processing_orders():
            market_order_id = int(remote["id"])
            market_created_at = _parse_market_datetime(remote.get("creationDate"))
            order = session.scalar(
                select(MarketOrder).where(
                    MarketOrder.account_id == account.id,
                    MarketOrder.market_order_id == market_order_id,
                )
            )
            is_new = order is None
            if order is None:
                order = MarketOrder(
                    account_id=account.id,
                    market_order_id=market_order_id,
                    status=str(remote.get("status") or "PROCESSING"),
                    substatus=str(remote.get("substatus") or "STARTED"),
                    items=list(remote.get("items") or []),
                    market_created_at=market_created_at,
                    shipment_date=_parse_shipment_date(remote),
                    last_seen_at=now,
                )
                session.add(order)
                session.flush()
            else:
                order.status = str(remote.get("status") or order.status)
                order.substatus = str(remote.get("substatus") or order.substatus or "") or None
                order.items = list(remote.get("items") or order.items)
                order.shipment_date = _parse_shipment_date(remote) or order.shipment_date
                if market_created_at is not None:
                    order.market_created_at = market_created_at
                order.last_seen_at = now
                if order.substatus == "STARTED" and order.pack_state == "failed":
                    order.pack_state = "available"
            if is_new and order.substatus == "STARTED":
                self._queue_new_order(session, order)
                order.notified_at = now
                created += 1

        ready_orders = list(
            session.scalars(
                select(MarketOrder).where(
                    MarketOrder.account_id == account.id,
                    MarketOrder.status == "PROCESSING",
                    MarketOrder.substatus == "READY_TO_SHIP",
                )
            )
        )
        for order in ready_orders:
            try:
                self._apply_remote_state(
                    order,
                    client.get_order(order.market_order_id),
                )
                order.last_seen_at = now
            except Exception as exc:  # noqa: BLE001 - one order must not stop polling
                logger.warning(
                    "Could not reconcile Yandex Market order %s: %s",
                    order.market_order_id,
                    exc,
                )
        account.last_polled_at = now
        account.last_error = None
        session.commit()
        return created

    def request_pack(
        self,
        session: Session,
        order_id: str,
        *,
        user_id: int,
        display_name: str,
    ) -> MarketOrder:
        order = session.scalar(
            select(MarketOrder)
            .where(MarketOrder.id == order_id)
            .with_for_update()
        )
        if order is None:
            raise LookupError("Market order not found")
        if order.pack_state == "packed" or order.substatus == "READY_TO_SHIP":
            return order
        if order.status != "PROCESSING" or order.substatus != "STARTED":
            raise RuntimeError("Заказ уже нельзя отметить как запакованный")
        if order.pack_state == "pending" and order.pack_requested_by != user_id:
            raise RuntimeError("Другой сборщик уже обрабатывает этот заказ")
        order.pack_state = "pending"
        order.pack_requested_by = user_id
        order.pack_requested_name = display_name[:160]
        order.pack_requested_at = datetime.now(UTC)
        order.pack_error = None
        return order

    def pack_request_payload(self, order: MarketOrder) -> dict:
        if order.pack_state == "packed":
            return packed_payload(order, admin=False)
        return pack_queued_payload(order)

    def available_orders(self, session: Session) -> list[MarketOrder]:
        return list(
            session.scalars(
                select(MarketOrder)
                .where(
                    MarketOrder.status == "PROCESSING",
                    MarketOrder.substatus == "STARTED",
                    MarketOrder.pack_state.in_(("available", "failed")),
                )
                .order_by(MarketOrder.discovered_at)
            )
        )

    def orders_payload(self, session: Session, *, can_pack: bool) -> dict:
        return orders_payload(self.available_orders(session), can_pack=can_pack)

    def orders_notification(self, session: Session) -> Notification:
        count = len(self.available_orders(session))
        return Notification(f"📦 Заказов к упаковке: {count}")

    def shipment_plan_notification(
        self,
        session: Session,
        *,
        now: datetime | None = None,
    ) -> Notification:
        # Imported lazily to keep the marketplace modules independently loadable.
        from ..ozon_seller.models import OzonPosting

        market_orders = list(
            session.scalars(
                select(MarketOrder).where(
                    MarketOrder.status == "PROCESSING",
                    MarketOrder.substatus.in_(("STARTED", "READY_TO_SHIP")),
                )
            )
        )
        ozon_postings = list(
            session.scalars(
                select(OzonPosting).where(
                    OzonPosting.scheme == "FBS",
                    OzonPosting.status.in_(("awaiting_packaging", "awaiting_deliver")),
                )
            )
        )

        today = (now or datetime.now(UTC)).astimezone(MARKET_TIMEZONE).date()
        tomorrow = today + timedelta(days=1)
        entries: list[tuple[str, str, list[dict]]] = []
        for order in market_orders:
            entries.append(
                (self._shipment_bucket(order.shipment_date, today), "market", order.items)
            )
        for posting in ozon_postings:
            shipment_date = posting.shipment_date
            if shipment_date is not None:
                if shipment_date.tzinfo is None:
                    shipment_date = shipment_date.replace(tzinfo=UTC)
                local_date = shipment_date.astimezone(MARKET_TIMEZONE).date()
            else:
                local_date = None
            entries.append(
                (self._shipment_bucket(local_date, today), "ozon", posting.products)
            )

        lines = ["📋 **План отправок**"]
        periods = (
            ("today", f"Сегодня и просрочено · {today:%d.%m}"),
            ("tomorrow", f"Завтра · {tomorrow:%d.%m}"),
            ("later", "Позже"),
            ("unknown", "Без указанной даты"),
        )
        for key, label in periods:
            period_entries = [entry for entry in entries if entry[0] == key]
            if key in {"today", "tomorrow"} or period_entries:
                self._append_plan_period(lines, label=label, entries=period_entries)
        lines.append("\nУчитываются FBS-заказы, которые ещё нужно собрать или передать.")
        return Notification("\n".join(lines))

    @staticmethod
    def _shipment_bucket(shipment_date: date | None, today: date) -> str:
        if shipment_date is None:
            return "unknown"
        if shipment_date <= today:
            return "today"
        if shipment_date == today + timedelta(days=1):
            return "tomorrow"
        return "later"

    @classmethod
    def _append_plan_period(
        cls,
        lines: list[str],
        *,
        label: str,
        entries: list[tuple[str, str, list[dict]]],
    ) -> None:
        market_entries = [items for _, platform, items in entries if platform == "market"]
        ozon_entries = [items for _, platform, items in entries if platform == "ozon"]
        total_items = cls._aggregate_items(
            cls._item_values(platform, item)
            for _, platform, items in entries
            for item in items
        )
        lines.append(
            f"\n📅 **{label}**\n"
            f"Посылок: **{len(entries)}** · товаров: **{sum(total_items.values())} шт.**"
        )
        cls._append_shipment_section(
            lines,
            title="🟡 Яндекс Маркет",
            entries=market_entries,
            platform="market",
        )
        cls._append_shipment_section(
            lines,
            title="🔵 Ozon",
            entries=ozon_entries,
            platform="ozon",
        )

    @staticmethod
    def _item_values(platform: str, item: dict) -> tuple[object, object]:
        if platform == "market":
            return item.get("offerName") or item.get("offerId") or "Товар", item.get("count")
        return item.get("name") or item.get("offer_id") or "Товар", item.get("quantity")

    @staticmethod
    def _aggregate_items(items: Iterable[tuple[object, object]]) -> dict[str, int]:
        totals: defaultdict[str, int] = defaultdict(int)
        for raw_name, raw_quantity in items:
            name = str(raw_name).strip() or "Товар"
            try:
                quantity = max(1, int(raw_quantity or 1))
            except (TypeError, ValueError):
                quantity = 1
            totals[name] += quantity
        return dict(sorted(totals.items(), key=lambda item: item[0].casefold()))

    @staticmethod
    def _append_shipment_section(
        lines: list[str],
        *,
        title: str,
        entries: list[list[dict]],
        platform: str,
    ) -> None:
        if not entries:
            return
        items = YandexMarketService._aggregate_items(
            YandexMarketService._item_values(platform, item)
            for order_items in entries
            for item in order_items
        )
        lines.append(f"\n{title} · **{len(entries)} пос.**")
        lines.extend(f"• {name} — **{quantity} шт.**" for name, quantity in items.items())

    def status_notification(self, session: Session) -> Notification:
        pending = session.scalar(
            select(func.count(MarketOrder.id)).where(MarketOrder.pack_state == "pending")
        ) or 0
        packed = session.scalar(
            select(func.count(MarketOrder.id)).where(MarketOrder.pack_state == "packed")
        ) or 0
        return Notification(f"📊 Яндекс Маркет\nВ работе: {pending}\nЗапаковано: {packed}")

    def process_pack(self, session: Session, order: MarketOrder) -> bool:
        account = self.account(session, order.account_id)
        client = self.client_factory(
            decrypt_secret(account.api_key_encrypted), account.campaign_id
        )
        try:
            remote = client.get_order(order.market_order_id)
            self._apply_remote_state(order, remote)
            if self._remote_pack_completed(order.status, order.substatus):
                self._finish_pack(session, account, order)
                return True
            if order.status != "PROCESSING" or order.substatus != "STARTED":
                raise RuntimeError(
                    "Заказ уже находится в состоянии "
                    f"{order.status}/{order.substatus or 'без подстатуса'}"
                )
            client.mark_ready_to_ship(order.market_order_id)
        except Exception as exc:  # noqa: BLE001 - persist any provider failure for retry
            # The order can advance between GET and PUT. Reconcile once before
            # reporting an error so an idempotent click never looks like a failure.
            try:
                remote = client.get_order(order.market_order_id)
                self._apply_remote_state(order, remote)
            except Exception as reconcile_exc:  # noqa: BLE001
                logger.warning(
                    "Could not reconcile Yandex Market order %s after update failure: %s",
                    order.market_order_id,
                    reconcile_exc,
                )
            if self._remote_pack_completed(order.status, order.substatus):
                self._finish_pack(session, account, order)
                return True
            order.pack_state = "failed"
            order.pack_attempts += 1
            detail = str(exc).strip() or type(exc).__name__
            order.pack_error = f"Yandex Market update failed: {detail}"[:1000]
            account.last_error = order.pack_error
            self._queue_pack_result(session, order, success=False)
            return False
        order.status = "PROCESSING"
        order.substatus = "READY_TO_SHIP"
        self._finish_pack(session, account, order)
        return True

    @staticmethod
    def _apply_remote_state(order: MarketOrder, remote: dict) -> None:
        order.status = str(remote.get("status") or order.status)
        order.substatus = str(remote.get("substatus") or "") or None
        order.shipment_date = _parse_shipment_date(remote) or order.shipment_date

    @staticmethod
    def _remote_pack_completed(status: str, substatus: str | None) -> bool:
        return substatus in {"READY_TO_SHIP", "SHIPPED"} or status in {
            "DELIVERY",
            "PICKUP",
            "DELIVERED",
        }

    def _finish_pack(
        self,
        session: Session,
        account: YandexMarketAccount,
        order: MarketOrder,
    ) -> None:
        order.pack_state = "packed"
        order.pack_attempts += 1
        order.packed_at = datetime.now(UTC)
        order.pack_error = None
        account.last_error = None
        self._queue_pack_result(session, order, success=True)

    def _queue_pack_result(
        self, session: Session, order: MarketOrder, *, success: bool
    ) -> None:
        for bot in self._market_bots(session):
            for target_type, target_id, role in self._recipients(session, bot):
                is_requester = target_type == "user" and target_id == order.pack_requested_by
                if role != "admin" and not is_requester:
                    continue
                payload = (
                    packed_payload(order, admin=role == "admin")
                    if success
                    else pack_failed_payload(order, admin=role == "admin")
                )
                session.add(
                    MaxOutboxMessage(
                        bot_id=bot.id,
                        target_type=target_type,
                        target_id=target_id,
                        payload=payload,
                    )
                )
