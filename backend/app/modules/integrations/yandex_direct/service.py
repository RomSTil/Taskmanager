import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ....security import decrypt_secret, encrypt_secret
from ...event_bus.events import BudgetRunningLow, DirectAnomalyDetected, ReportGenerated
from ...event_bus.models import DomainEvent
from ...event_bus.service import EventBusService
from ...notifications.service import Notification
from .client import YandexDirectClient
from .models import (
    DirectCampaignSnapshot,
    DirectDailyStat,
    IntegrationJob,
    YandexDirectAccount,
)
from .repository import YandexDirectRepository
from .schemas import DirectAccountCreate, DirectAccountUpdate, DirectJobCreate


ClientFactory = Callable[[str, str | None], YandexDirectClient]


class YandexDirectService:
    def __init__(
        self,
        event_bus: EventBusService,
        *,
        repository: YandexDirectRepository | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.event_bus = event_bus
        self.repository = repository or YandexDirectRepository()
        self.client_factory = client_factory or (
            lambda token, login: YandexDirectClient(token, client_login=login)
        )

    def account(self, session: Session, account_id: str) -> YandexDirectAccount:
        account = session.get(YandexDirectAccount, account_id)
        if account is None:
            raise LookupError("Yandex Direct account not found")
        return account

    def create_account(
        self, session: Session, payload: DirectAccountCreate
    ) -> YandexDirectAccount:
        account = YandexDirectAccount(
            name=payload.name,
            client_login=payload.client_login,
            token_encrypted=encrypt_secret(payload.token),
            token_hint=f"…{payload.token[-6:]}",
            enabled=payload.enabled,
            balance_threshold=payload.balance_threshold,
            days_left_threshold=payload.days_left_threshold,
            anomaly_ratio=payload.anomaly_ratio,
            monitor_interval_minutes=payload.monitor_interval_minutes,
        )
        session.add(account)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise ValueError("Yandex Direct account name already exists") from exc
        session.refresh(account)
        return account

    def update_account(
        self,
        session: Session,
        account_id: str,
        payload: DirectAccountUpdate,
    ) -> YandexDirectAccount:
        account = self.account(session, account_id)
        if account.version != payload.base_version:
            raise RuntimeError("Yandex Direct account version conflict")
        for field in (
            "name",
            "client_login",
            "balance_threshold",
            "days_left_threshold",
            "anomaly_ratio",
            "monitor_interval_minutes",
            "enabled",
        ):
            if field in payload.model_fields_set:
                setattr(account, field, getattr(payload, field))
        if payload.token:
            account.token_encrypted = encrypt_secret(payload.token)
            account.token_hint = f"…{payload.token[-6:]}"
        account.version += 1
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise ValueError("Yandex Direct account name already exists") from exc
        session.refresh(account)
        return account

    def queue_job(
        self,
        session: Session,
        account: YandexDirectAccount,
        job_type: str,
        *,
        payload: dict | None = None,
        idempotency_key: str | None = None,
    ) -> IntegrationJob:
        payload = payload or {}
        key = idempotency_key or f"direct:{account.id}:{job_type}:{uuid.uuid4()}"
        existing = session.scalar(
            select(IntegrationJob).where(IntegrationJob.idempotency_key == key)
        )
        if existing:
            return existing
        job = IntegrationJob(
            provider="yandex_direct",
            job_type=job_type,
            account_id=account.id,
            payload=payload,
            idempotency_key=key,
        )
        session.add(job)
        session.flush()
        return job

    def queue_requested_job(
        self,
        session: Session,
        account_id: str,
        payload: DirectJobCreate,
    ) -> IntegrationJob:
        account = self.account(session, account_id)
        job_payload: dict[str, str] = {}
        if payload.date_from:
            job_payload["date_from"] = payload.date_from.isoformat()
        if payload.date_to:
            job_payload["date_to"] = payload.date_to.isoformat()
        job = self.queue_job(session, account, payload.job_type, payload=job_payload)
        session.commit()
        session.refresh(job)
        return job

    def perform_job(self, session: Session, job: IntegrationJob) -> dict:
        if not job.account_id:
            raise LookupError("Direct job has no account")
        account = self.account(session, job.account_id)
        client = self.client_factory(decrypt_secret(account.token_encrypted), account.client_login)
        today = datetime.now(UTC).date()
        if job.job_type == "campaign_sync":
            campaigns = self.repository.save_campaigns(session, account, client.get_campaigns())
            return {"campaigns": len(campaigns)}
        if job.job_type in {"balance_check", "report"}:
            date_to = date.fromisoformat(job.payload.get("date_to", today.isoformat()))
            default_from = date_to - timedelta(days=7)
            date_from = date.fromisoformat(
                job.payload.get("date_from", default_from.isoformat())
            )
            campaigns = self.repository.save_campaigns(session, account, client.get_campaigns())
            rows = client.get_report(
                date_from,
                date_to,
                campaign_ids=[campaign.campaign_id for campaign in campaigns],
            )
            stats = self.repository.save_stats(session, account, rows)
            if job.job_type == "report":
                self.event_bus.publish(
                    session,
                    ReportGenerated(
                        account_id=account.id,
                        account_name=account.name,
                        date_from=date_from.isoformat(),
                        date_to=date_to.isoformat(),
                        rows=len(stats),
                    ),
                    deduplication_key=f"ReportGenerated:{job.id}",
                )
            result = self._analyze(session, account, campaigns, stats, date_from, date_to)
            result["campaigns"] = len(campaigns)
            result["rows"] = len(stats)
            return result
        raise ValueError(f"Unsupported Direct job type: {job.job_type}")

    def _analyze(
        self,
        session: Session,
        account: YandexDirectAccount,
        campaigns: list[DirectCampaignSnapshot],
        stats: list[DirectDailyStat],
        date_from: date,
        date_to: date,
    ) -> dict:
        known_balances = [campaign.balance for campaign in campaigns if campaign.balance is not None]
        balance = sum(known_balances, start=Decimal("0"))
        currency = next((campaign.currency for campaign in campaigns if campaign.currency), "")
        costs_by_date: dict[date, Decimal] = {}
        for stat in stats:
            costs_by_date[stat.stat_date] = costs_by_date.get(stat.stat_date, Decimal("0")) + stat.cost
        total_days = max(1, (date_to - date_from).days)
        previous_cost = sum(
            (cost for stat_date, cost in costs_by_date.items() if stat_date < date_to),
            start=Decimal("0"),
        )
        average_daily_cost = previous_cost / Decimal(total_days)
        days_left = float(balance / average_daily_cost) if average_daily_cost > 0 else None
        low_by_balance = bool(known_balances) and balance <= account.balance_threshold
        low_by_days = (
            days_left is not None and days_left <= float(account.days_left_threshold)
        )
        if low_by_balance or low_by_days:
            self.event_bus.publish(
                session,
                BudgetRunningLow(
                    account_id=account.id,
                    account_name=account.name,
                    balance=float(balance),
                    currency=currency,
                    days_left=days_left,
                    threshold=float(account.balance_threshold),
                ),
                deduplication_key=f"BudgetRunningLow:{account.id}:{date_to.isoformat()}",
            )
        today_cost = costs_by_date.get(date_to, Decimal("0"))
        if (
            average_daily_cost > 0
            and today_cost > average_daily_cost * account.anomaly_ratio
        ):
            self.event_bus.publish(
                session,
                DirectAnomalyDetected(
                    account_id=account.id,
                    account_name=account.name,
                    metric="Расход за сегодня",
                    actual=float(today_cost),
                    baseline=float(average_daily_cost),
                    ratio=float(today_cost / average_daily_cost),
                ),
                deduplication_key=f"DirectAnomalyDetected:{account.id}:cost:{date_to.isoformat()}",
            )
        account.last_checked_at = datetime.now(UTC)
        account.last_error = None
        return {
            "balance": float(balance) if known_balances else None,
            "currency": currency,
            "average_daily_cost": float(average_daily_cost),
            "days_left": days_left,
            "shared_account_campaigns": sum(
                1 for campaign in campaigns if campaign.uses_shared_account
            ),
        }

    def balance_notification(self, session: Session) -> Notification:
        accounts = list(
            session.scalars(
                select(YandexDirectAccount)
                .where(YandexDirectAccount.enabled.is_(True))
                .order_by(YandexDirectAccount.name)
            )
        )
        lines: list[str] = ["💰 Баланс Яндекс Директа"]
        for account in accounts:
            campaigns = list(
                session.scalars(
                    select(DirectCampaignSnapshot).where(
                        DirectCampaignSnapshot.account_id == account.id
                    )
                )
            )
            known = [item.balance for item in campaigns if item.balance is not None]
            if known:
                currency = next((item.currency for item in campaigns if item.currency), "")
                lines.append(f"{account.name}: {sum(known, Decimal('0')):.2f} {currency}")
            else:
                lines.append(f"{account.name}: общий счёт или данные ещё не загружены")
            self.queue_job(
                session,
                account,
                "balance_check",
                idempotency_key=(
                    f"direct:{account.id}:manual-balance:"
                    f"{datetime.now(UTC).strftime('%Y%m%d%H%M')}"
                ),
            )
        session.commit()
        if not accounts:
            return Notification("Аккаунт Яндекс Директа ещё не настроен.", "warning")
        lines.append("Обновление поставлено в очередь.")
        return Notification("\n".join(lines))

    def today_notification(self, session: Session) -> Notification:
        today = datetime.now(UTC).date()
        rows = session.execute(
            select(
                func.coalesce(func.sum(DirectDailyStat.impressions), 0),
                func.coalesce(func.sum(DirectDailyStat.clicks), 0),
                func.coalesce(func.sum(DirectDailyStat.cost), 0),
                func.coalesce(func.sum(DirectDailyStat.conversions), 0),
            ).where(DirectDailyStat.stat_date == today)
        ).one()
        return Notification(
            "📊 Яндекс Директ сегодня\n"
            f"Показы: {int(rows[0])}\n"
            f"Клики: {int(rows[1])}\n"
            f"Расход: {Decimal(rows[2]):.2f}\n"
            f"Конверсии: {Decimal(rows[3]):.2f}"
        )

    def campaigns_notification(self, session: Session) -> Notification:
        campaigns = list(
            session.scalars(
                select(DirectCampaignSnapshot)
                .order_by(DirectCampaignSnapshot.checked_at.desc())
                .limit(10)
            )
        )
        if not campaigns:
            return Notification("Кампании ещё не загружены. Запустите проверку баланса.", "warning")
        lines = ["📈 Кампании"]
        lines.extend(
            f"• {item.name} — {item.state}/{item.status}"
            for item in campaigns
        )
        return Notification("\n".join(lines))

    def report_notification(self, session: Session) -> Notification:
        accounts = list(
            session.scalars(
                select(YandexDirectAccount).where(YandexDirectAccount.enabled.is_(True))
            )
        )
        today = datetime.now(UTC).date()
        for account in accounts:
            self.queue_job(
                session,
                account,
                "report",
                payload={
                    "date_from": (today - timedelta(days=7)).isoformat(),
                    "date_to": today.isoformat(),
                },
            )
        session.commit()
        return Notification(
            "📄 Отчёт за 7 дней поставлен в очередь."
            if accounts
            else "Аккаунт Яндекс Директа ещё не настроен.",
            "info" if accounts else "warning",
        )

    def alerts_notification(self, session: Session) -> Notification:
        events = list(
            session.scalars(
                select(DomainEvent)
                .where(
                    DomainEvent.event_type.in_(
                        ["BudgetRunningLow", "DirectAnomalyDetected"]
                    )
                )
                .order_by(DomainEvent.created_at.desc())
                .limit(5)
            )
        )
        if not events:
            return Notification("⚠️ Активных алертов нет.")
        lines = ["⚠️ Последние алерты"]
        lines.extend(
            f"• {event.event_type}: {event.payload.get('account_name', event.aggregate_id)}"
            for event in events
        )
        return Notification("\n".join(lines), "warning")

    def settings_notification(self, session: Session) -> Notification:
        accounts = list(session.scalars(select(YandexDirectAccount).order_by(YandexDirectAccount.name)))
        if not accounts:
            return Notification("⚙️ Аккаунты Яндекс Директа не настроены.", "warning")
        lines = ["⚙️ Настройки мониторинга"]
        lines.extend(
            f"• {account.name}: каждые {account.monitor_interval_minutes} мин., "
            f"порог {account.balance_threshold}"
            for account in accounts
        )
        return Notification("\n".join(lines))
