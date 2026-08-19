from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import OzonSellerAccount
from .service import OzonSellerService


def sync_due_accounts(session: Session, service: OzonSellerService) -> int:
    now = datetime.now(UTC)
    completed = 0
    accounts = list(
        session.scalars(
            select(OzonSellerAccount).where(OzonSellerAccount.enabled.is_(True))
        )
    )
    for account in accounts:
        due_before = now - timedelta(minutes=account.poll_interval_minutes)
        checked_at = account.last_checked_at
        if checked_at is not None:
            if checked_at.tzinfo is None:
                checked_at = checked_at.replace(tzinfo=UTC)
            if checked_at > due_before:
                continue
        try:
            service.sync_account(session, account, now=now)
            completed += 1
        except Exception as exc:
            session.rollback()
            stored = session.get(OzonSellerAccount, account.id)
            if stored:
                stored.last_error = str(exc)[:1000]
                stored.last_checked_at = now
                session.commit()
    return completed
