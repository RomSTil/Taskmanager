from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ....security import decrypt_secret, encrypt_secret
from ...event_bus.events import OzonOrderCreated
from ...event_bus.service import EventBusService
from ...notifications.service import Notification, ozon_status_label
from .client import OzonSellerClient
from .models import OzonPosting, OzonSellerAccount
from .schemas import OzonAccountCreate

ClientFactory = Callable[[str, str], OzonSellerClient]
MARKETPLACE_TIMEZONE = ZoneInfo("Europe/Moscow")


def _datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _local_datetime(value: datetime | None, *, with_time: bool = False) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    pattern = "%d.%m.%Y, %H:%M" if with_time else "%d.%m.%Y"
    return value.astimezone(MARKETPLACE_TIMEZONE).strftime(pattern)


def _plain(value: object, fallback: str = "") -> str:
    text = str(value or fallback).strip()
    for character in "*_[`]":
        text = text.replace(character, "")
    return text


class OzonSellerService:
    def __init__(
        self,
        event_bus: EventBusService,
        *,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.event_bus = event_bus
        self.client_factory = client_factory or (
            lambda client_id, api_key: OzonSellerClient(client_id, api_key)
        )

    def account(self, session: Session, account_id: str) -> OzonSellerAccount:
        account = session.get(OzonSellerAccount, account_id)
        if account is None:
            raise LookupError("Ozon Seller account not found")
        return account

    def create_account(
        self,
        session: Session,
        payload: OzonAccountCreate,
    ) -> OzonSellerAccount:
        account = OzonSellerAccount(
            name=payload.name,
            client_id=payload.client_id,
            api_key_encrypted=encrypt_secret(payload.api_key),
            api_key_hint=f"...{payload.api_key[-6:]}",
            enabled=payload.enabled,
            poll_interval_minutes=payload.poll_interval_minutes,
        )
        session.add(account)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise ValueError("Ozon Seller account name already exists") from exc
        session.refresh(account)
        return account

    def sync_account(
        self,
        session: Session,
        account: OzonSellerAccount,
        *,
        now: datetime | None = None,
    ) -> dict[str, object]:
        now = now or datetime.now(UTC)
        baseline = not account.baseline_completed
        notify_after = account.last_checked_at
        if notify_after is not None and notify_after.tzinfo is None:
            notify_after = notify_after.replace(tzinfo=UTC)
        # Ozon filters postings by their creation date, not by the date of the
        # latest status change. Keep the lookback window so completed postings
        # disappear from shipment plans after subsequent syncs.
        since = now - timedelta(days=30)
        client = self.client_factory(
            account.client_id,
            decrypt_secret(account.api_key_encrypted),
        )
        batches = (
            ("FBS", client.list_fbs_postings(since, now)),
            ("FBO", client.list_fbo_postings(since, now)),
        )
        fetched = sum(len(items) for _, items in batches)
        created = 0
        notified = 0
        for scheme, items in batches:
            for item in items:
                posting_number = str(
                    item.get("posting_number") or item.get("order_number") or ""
                ).strip()
                if not posting_number:
                    continue
                existing = session.scalar(
                    select(OzonPosting).where(
                        OzonPosting.account_id == account.id,
                        OzonPosting.scheme == scheme,
                        OzonPosting.posting_number == posting_number,
                    )
                )
                if existing:
                    products = self._products(item)
                    existing.status = str(item.get("status") or existing.status)
                    existing.products = products or existing.products
                    existing.total = sum(
                        (
                            _decimal(product.get("price"))
                            * int(product.get("quantity") or 0)
                        )
                        for product in existing.products
                    )
                    existing.currency = next(
                        (
                            str(product.get("currency_code"))
                            for product in existing.products
                            if product.get("currency_code")
                        ),
                        existing.currency,
                    )
                    existing.shipment_date = (
                        _datetime(item.get("shipment_date")) or existing.shipment_date
                    )
                    continue
                products = self._products(item)
                total = sum(
                    (_decimal(product.get("price")) * int(product.get("quantity") or 0))
                    for product in products
                )
                currency = next(
                    (
                        str(product.get("currency_code"))
                        for product in products
                        if product.get("currency_code")
                    ),
                    "RUB",
                )
                posting = OzonPosting(
                    account_id=account.id,
                    scheme=scheme,
                    posting_number=posting_number,
                    order_number=str(item.get("order_number") or "") or None,
                    status=str(item.get("status") or "unknown"),
                    products=products,
                    total=total,
                    currency=currency,
                    ozon_created_at=_datetime(item.get("created_at") or item.get("in_process_at")),
                    shipment_date=_datetime(item.get("shipment_date")),
                )
                session.add(posting)
                session.flush()
                created += 1
                if baseline or (
                    notify_after is not None
                    and posting.ozon_created_at is not None
                    and posting.ozon_created_at <= notify_after
                ):
                    continue
                self.event_bus.publish(
                    session,
                    OzonOrderCreated(
                        account_id=account.id,
                        account_name=account.name,
                        posting_number=posting.posting_number,
                        order_number=posting.order_number,
                        scheme=posting.scheme,
                        status=posting.status,
                        products=posting.products,
                        total=float(posting.total),
                        currency=posting.currency,
                        created_at=(
                            posting.ozon_created_at.isoformat()
                            if posting.ozon_created_at
                            else None
                        ),
                        shipment_date=(
                            posting.shipment_date.isoformat()
                            if posting.shipment_date
                            else None
                        ),
                    ),
                    deduplication_key=(
                        f"OzonOrderCreated:{account.id}:{scheme}:{posting_number}"
                    ),
                )
                notified += 1
        account.baseline_completed = True
        account.last_checked_at = now
        account.last_error = None
        session.commit()
        return {
            "account_id": account.id,
            "fetched": fetched,
            "created": created,
            "notified": notified,
            "baseline": baseline,
        }

    def recent_orders_notification(self, session: Session) -> Notification:
        postings = list(
            session.scalars(
                select(OzonPosting)
                .order_by(OzonPosting.first_seen_at.desc())
                .limit(10)
            )
        )
        if not postings:
            return Notification("📦 **Ozon Seller**\nЗаказы ещё не загружены.", "warning")
        lines = ["📦 **Последние заказы Ozon**"]
        for posting in postings:
            quantity = sum(int(item.get("quantity") or 0) for item in posting.products)
            lines.append(f"\n🔵 **Ozon — заказ №{_plain(posting.posting_number)}**")
            if created_at := _local_datetime(posting.ozon_created_at):
                lines.append(f"📅 Дата заказа: **{created_at}**")
            lines.append(f"🔢 Количество штук: **{quantity}**")
            for product in posting.products:
                name = _plain(product.get("name") or product.get("offer_id"), "Товар")
                product_quantity = max(1, int(product.get("quantity") or 1))
                suffix = f" × {product_quantity}" if product_quantity > 1 else ""
                lines.append(f"• {name}{suffix}")
            lines.append(f"📌 Статус: **{ozon_status_label(posting.status)}**")
            if shipment_date := _local_datetime(posting.shipment_date, with_time=True):
                lines.append(f"⏰ Отгрузить до: **{shipment_date} (МСК)**")
            lines.append(
                f"🚚 Схема: **{_plain(posting.scheme)}** · "
                f"💰 **{posting.total:.2f} {_plain(posting.currency, 'RUB')}**"
            )
        return Notification("\n".join(lines))

    def refresh_notification(self, session: Session) -> Notification:
        accounts = list(
            session.scalars(
                select(OzonSellerAccount).where(OzonSellerAccount.enabled.is_(True))
            )
        )
        if not accounts:
            return Notification(
                "⚙️ Ozon Seller не подключён. Добавьте Client-Id и Api-Key в интеграциях.",
                "warning",
            )
        fetched = created = notified = 0
        errors: list[str] = []
        for account in accounts:
            try:
                result = self.sync_account(session, account)
            except Exception as exc:
                session.rollback()
                stored = session.get(OzonSellerAccount, account.id)
                if stored:
                    stored.last_error = str(exc)[:1000]
                    session.commit()
                errors.append(f"{account.name}: {exc}")
                continue
            fetched += int(result["fetched"])
            created += int(result["created"])
            notified += int(result["notified"])
        text = (
            "🔄 **Ozon Seller обновлён**\n"
            f"Получено: {fetched}\nНовых: {created}\nУведомлений: {notified}"
        )
        if errors:
            text += "\n\n⚠️ " + "\n".join(errors[:3])
        return Notification(text, "warning" if errors else "info")

    @staticmethod
    def _products(item: dict) -> list[dict]:
        products: list[dict] = []
        for product in item.get("products") or []:
            if not isinstance(product, dict):
                continue
            products.append(
                {
                    "name": str(product.get("name") or product.get("offer_id") or "Товар"),
                    "offer_id": str(product.get("offer_id") or ""),
                    "sku": str(product.get("sku") or ""),
                    "quantity": int(product.get("quantity") or 0),
                    "price": str(product.get("price") or "0"),
                    "currency_code": str(product.get("currency_code") or "RUB"),
                }
            )
        return products
