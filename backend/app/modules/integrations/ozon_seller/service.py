from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ....security import decrypt_secret, encrypt_secret
from ...event_bus.events import OzonOrderCreated
from ...event_bus.service import EventBusService
from ...notifications.service import Notification
from .client import OzonSellerClient
from .models import OzonPosting, OzonSellerAccount
from .schemas import OzonAccountCreate


ClientFactory = Callable[[str, str], OzonSellerClient]


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
        since = now - timedelta(days=30)
        if account.last_checked_at is not None:
            checked_at = account.last_checked_at
            if checked_at.tzinfo is None:
                checked_at = checked_at.replace(tzinfo=UTC)
            since = checked_at - timedelta(minutes=10)
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
                    select(OzonPosting.id).where(
                        OzonPosting.account_id == account.id,
                        OzonPosting.scheme == scheme,
                        OzonPosting.posting_number == posting_number,
                    )
                )
                if existing:
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
                if baseline:
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
            lines.append(
                f"• `{posting.posting_number}` · {posting.scheme} · "
                f"{quantity} шт. · {posting.total:.2f} {posting.currency}"
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
