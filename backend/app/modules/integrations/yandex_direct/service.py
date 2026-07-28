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
            shared_account = None
            if any(campaign.uses_shared_account for campaign in campaigns):
                shared_account = client.get_shared_account()
            rows = client.get_report(
                date_from,
                date_to,
                campaign_ids=[campaign.campaign_id for campaign in campaigns],
            )
            stats = self.repository.save_stats(session, account, rows)
            result = self._analyze(
                session,
                account,
                campaigns,
                stats,
                date_from,
                date_to,
                shared_account=shared_account,
            )
            result["campaigns"] = len(campaigns)
            result["rows"] = len(stats)
            if job.job_type == "report":
                impressions = sum(item.impressions for item in stats)
                clicks = sum(item.clicks for item in stats)
                cost = sum((item.cost for item in stats), start=Decimal("0"))
                conversions = sum(
                    (item.conversions for item in stats), start=Decimal("0")
                )
                self.event_bus.publish(
                    session,
                    ReportGenerated(
                        account_id=account.id,
                        account_name=account.name,
                        date_from=date_from.isoformat(),
                        date_to=date_to.isoformat(),
                        rows=len(stats),
                        impressions=impressions,
                        clicks=clicks,
                        cost=float(cost),
                        conversions=float(conversions),
                    ),
                    deduplication_key=f"ReportGenerated:{job.id}",
                )
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
        *,
        shared_account: dict | None = None,
    ) -> dict:
        known_balances = [
            campaign.balance
            for campaign in campaigns
            if campaign.balance is not None
        ]
        shared_balance = (
            Decimal(str(shared_account["Amount"]))
            if shared_account and shared_account.get("Amount") is not None
            else None
        )
        balance = sum(known_balances, start=Decimal("0"))
        if shared_balance is not None:
            balance += shared_balance
        has_balance = bool(known_balances) or shared_balance is not None
        currency = (
            str(shared_account.get("Currency") or "")
            if shared_account
            else next((campaign.currency for campaign in campaigns if campaign.currency), "")
        )
        costs_by_date: dict[date, Decimal] = {}
        for stat in stats:
            costs_by_date[stat.stat_date] = (
                costs_by_date.get(stat.stat_date, Decimal("0")) + stat.cost
            )
        total_days = max(1, (date_to - date_from).days)
        previous_cost = sum(
            (cost for stat_date, cost in costs_by_date.items() if stat_date < date_to),
            start=Decimal("0"),
        )
        average_daily_cost = previous_cost / Decimal(total_days)
        days_left = (
            float(balance / average_daily_cost)
            if has_balance and average_daily_cost > 0
            else None
        )
        low_by_balance = has_balance and balance <= account.balance_threshold
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
            "balance": float(balance) if has_balance else None,
            "currency": currency,
            "balance_source": (
                "shared_account"
                if shared_balance is not None
                else "campaigns" if known_balances else None
            ),
            "amount_available_for_transfer": (
                float(shared_account["AmountAvailableForTransfer"])
                if shared_account
                and shared_account.get("AmountAvailableForTransfer") is not None
                else None
            ),
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
            shared = any(item.uses_shared_account for item in campaigns)
            shared_account = None
            shared_error = None
            if shared:
                try:
                    client = self.client_factory(
                        decrypt_secret(account.token_encrypted),
                        account.client_login,
                    )
                    shared_account = client.get_shared_account()
                except Exception as exc:  # noqa: BLE001
                    shared_error = str(exc)
            if shared_account and shared_account.get("Amount") is not None:
                amount = Decimal(str(shared_account["Amount"]))
                currency = str(shared_account.get("Currency") or "")
                transfer = shared_account.get("AmountAvailableForTransfer")
                lines.append(f"{account.name}: {amount:.2f} {currency}")
                if transfer is not None:
                    lines.append(f"Доступно к переносу: {Decimal(str(transfer)):.2f} {currency}")
            elif known:
                currency = next((item.currency for item in campaigns if item.currency), "")
                lines.append(f"{account.name}: {sum(known, Decimal('0')):.2f} {currency}")
            elif shared_error:
                lines.append(f"{account.name}: не удалось запросить общий счёт — {shared_error}")
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
        lines.append("Фоновое обновление статистики поставлено в очередь.")
        return Notification("\n".join(lines))

    @staticmethod
    def _number(value: Decimal | float | int, places: int = 2) -> str:
        return f"{float(value):,.{places}f}".replace(",", " ")

    def _period_totals(
        self,
        session: Session,
        *,
        days: int,
    ) -> tuple[date, date, int, int, Decimal, Decimal, datetime | None]:
        date_to = datetime.now(UTC).date()
        date_from = date_to - timedelta(days=days - 1)
        rows = session.execute(
            select(
                func.coalesce(func.sum(DirectDailyStat.impressions), 0),
                func.coalesce(func.sum(DirectDailyStat.clicks), 0),
                func.coalesce(func.sum(DirectDailyStat.cost), 0),
                func.coalesce(func.sum(DirectDailyStat.conversions), 0),
                func.max(DirectDailyStat.updated_at),
            ).where(
                DirectDailyStat.stat_date >= date_from,
                DirectDailyStat.stat_date <= date_to,
            )
        ).one()
        return (
            date_from,
            date_to,
            int(rows[0]),
            int(rows[1]),
            Decimal(rows[2]),
            Decimal(rows[3]),
            rows[4],
        )

    def _period_notification(
        self,
        session: Session,
        *,
        days: int,
        title: str,
    ) -> Notification:
        date_from, date_to, impressions, clicks, cost, conversions, updated_at = (
            self._period_totals(session, days=days)
        )
        ctr = Decimal(clicks * 100) / Decimal(impressions) if impressions else Decimal("0")
        cpc = cost / Decimal(clicks) if clicks else Decimal("0")
        conversion_rate = (
            conversions * Decimal("100") / Decimal(clicks)
            if clicks
            else Decimal("0")
        )
        cpa = cost / conversions if conversions else Decimal("0")
        average_cost = cost / Decimal(days)
        period = (
            date_to.strftime("%d.%m.%Y")
            if days == 1
            else f"{date_from.strftime('%d.%m')}–{date_to.strftime('%d.%m.%Y')}"
        )
        if updated_at is None:
            freshness = "данные ещё не загружены"
        else:
            display = (
                updated_at.replace(tzinfo=UTC)
                if updated_at.tzinfo is None
                else updated_at.astimezone(UTC)
            )
            freshness = display.strftime("%d.%m.%Y %H:%M UTC")
        return Notification(
            f"{title}\n"
            f"Период: {period}\n\n"
            f"👁 Показы: {impressions:,}\n"
            f"🖱 Клики: {clicks:,}\n"
            f"📈 CTR: {self._number(ctr)}%\n"
            f"💳 Расход: {self._number(cost)}\n"
            f"💵 Средний CPC: {self._number(cpc)}\n"
            f"🎯 Конверсии: {self._number(conversions)}\n"
            f"✅ CR: {self._number(conversion_rate)}%\n"
            f"🧾 CPA: {self._number(cpa)}\n"
            f"📅 Средний расход/день: {self._number(average_cost)}\n\n"
            f"Обновлено: {freshness}",
            "warning" if updated_at is None else "info",
        )

    def overview_notification(self, session: Session) -> Notification:
        lines = ["📊 Сводка Яндекс Директа"]
        has_data = False
        for days, label in ((1, "Сегодня"), (7, "7 дней"), (30, "30 дней")):
            _, _, impressions, clicks, cost, conversions, updated_at = (
                self._period_totals(session, days=days)
            )
            has_data = has_data or updated_at is not None
            ctr = clicks / impressions * 100 if impressions else 0
            lines.extend(
                [
                    "",
                    f"**{label}**",
                    f"{impressions:,} показов · {clicks:,} кликов · CTR {ctr:.2f}%",
                    f"{self._number(cost)} расход · {self._number(conversions)} конверсий",
                ]
            )
        if not has_data:
            lines.extend(
                [
                    "",
                    "Данные ещё не загружены.",
                    "Нажмите «🔄 Обновить данные».",
                ]
            )
        return Notification("\n".join(lines), "warning" if not has_data else "info")

    def today_notification(self, session: Session) -> Notification:
        return self._period_notification(
            session,
            days=1,
            title="📊 Яндекс Директ сегодня",
        )

    def week_notification(self, session: Session) -> Notification:
        return self._period_notification(
            session,
            days=7,
            title="📊 Яндекс Директ за 7 дней",
        )

    def month_notification(self, session: Session) -> Notification:
        return self._period_notification(
            session,
            days=30,
            title="📊 Яндекс Директ за 30 дней",
        )

    def campaigns_notification(self, session: Session) -> Notification:
        date_from = datetime.now(UTC).date() - timedelta(days=29)
        rows = list(
            session.execute(
                select(
                    DirectCampaignSnapshot.name,
                    DirectCampaignSnapshot.state,
                    DirectCampaignSnapshot.status,
                    func.coalesce(func.sum(DirectDailyStat.impressions), 0),
                    func.coalesce(func.sum(DirectDailyStat.clicks), 0),
                    func.coalesce(func.sum(DirectDailyStat.cost), 0),
                    func.coalesce(func.sum(DirectDailyStat.conversions), 0),
                )
                .outerjoin(
                    DirectDailyStat,
                    (
                        DirectDailyStat.account_id
                        == DirectCampaignSnapshot.account_id
                    )
                    & (
                        DirectDailyStat.campaign_id
                        == DirectCampaignSnapshot.campaign_id
                    )
                    & (DirectDailyStat.stat_date >= date_from),
                )
                .group_by(
                    DirectCampaignSnapshot.id,
                    DirectCampaignSnapshot.name,
                    DirectCampaignSnapshot.state,
                    DirectCampaignSnapshot.status,
                )
                .order_by(func.sum(DirectDailyStat.cost).desc())
                .limit(10)
            )
        )
        if not rows:
            return Notification(
                "Кампании ещё не загружены. Нажмите «🔄 Обновить данные».",
                "warning",
            )
        lines = ["📈 Кампании · последние 30 дней"]
        lines.extend(
            (
                f"\n• **{name}** · {state}/{status}\n"
                f"  {int(impressions):,} показов · {int(clicks):,} кликов · "
                f"{self._number(Decimal(cost))} расход · "
                f"{self._number(Decimal(conversions))} конверсий"
            )
            for name, state, status, impressions, clicks, cost, conversions in rows
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
                    "date_from": (today - timedelta(days=29)).isoformat(),
                    "date_to": today.isoformat(),
                },
            )
        session.commit()
        return Notification(
            "🔄 Обновление запущено.\n"
            "Запрашиваю кампании и метрики за 30 дней. "
            "Когда Яндекс Директ подготовит отчёт, бот пришлёт результат автоматически."
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
        accounts = list(
            session.scalars(
                select(YandexDirectAccount).order_by(YandexDirectAccount.name)
            )
        )
        if not accounts:
            return Notification("⚙️ Аккаунты Яндекс Директа не настроены.", "warning")
        lines = ["⚙️ Настройки мониторинга"]
        lines.extend(
            f"• {account.name}: каждые {account.monitor_interval_minutes} мин., "
            f"порог {account.balance_threshold}"
            for account in accounts
        )
        return Notification("\n".join(lines))
