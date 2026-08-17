from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import MarketOrder, YandexMarketAccount
from .service import YandexMarketService


def sync_due_market_accounts(session: Session, service: YandexMarketService) -> int:
    now = datetime.now(UTC)
    accounts = list(
        session.scalars(
            select(YandexMarketAccount).where(YandexMarketAccount.enabled.is_(True))
        )
    )
    synced = 0
    for account in accounts:
        due_at = (
            account.last_polled_at + timedelta(seconds=account.poll_interval_seconds)
            if account.last_polled_at
            else now
        )
        if due_at > now:
            continue
        try:
            service.sync_account(session, account)
            synced += 1
        except Exception as exc:  # noqa: BLE001 - one account must not stop the worker
            session.rollback()
            stored = session.get(YandexMarketAccount, account.id)
            if stored is not None:
                stored.last_polled_at = now
                stored.last_error = f"Yandex Market sync failed ({type(exc).__name__})"
                session.commit()
    return synced


def process_market_pack_requests(
    session: Session, service: YandexMarketService, *, limit: int = 20
) -> int:
    orders = list(
        session.scalars(
            select(MarketOrder)
            .where(MarketOrder.pack_state == "pending")
            .order_by(MarketOrder.pack_requested_at)
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
    )
    completed = 0
    for order in orders:
        if service.process_pack(session, order):
            completed += 1
        session.commit()
    return completed
