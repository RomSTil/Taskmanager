from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..event_bus.models import DomainEvent


@dataclass(frozen=True, slots=True)
class Notification:
    text: str
    severity: str = "info"


@dataclass(frozen=True, slots=True)
class MenuAction:
    action: str
    label: str
    row: int


InteractionHandler = Callable[[Session], Notification]


class InteractionRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, InteractionHandler] = {}
        self._actions: list[MenuAction] = []

    def register(
        self,
        action: str,
        label: str,
        handler: InteractionHandler,
        *,
        row: int,
    ) -> None:
        if action in self._handlers:
            raise ValueError(f"Interaction is already registered: {action}")
        self._handlers[action] = handler
        self._actions.append(MenuAction(action=action, label=label, row=row))

    def handle(self, action: str, session: Session) -> Notification:
        try:
            handler = self._handlers[action]
        except KeyError:
            return Notification("Действие пока недоступно.", "warning")
        return handler(session)

    def label_for(self, action: str) -> str:
        return next(
            (item.label for item in self._actions if item.action == action),
            "данные",
        )

    def menu_rows(self, prefix: str | None = None) -> list[list[MenuAction]]:
        rows: dict[int, list[MenuAction]] = {}
        actions = self._actions
        if prefix:
            actions = [action for action in actions if action.action.startswith(f"{prefix}.")]
        for action in actions:
            rows.setdefault(action.row, []).append(action)
        return [rows[row] for row in sorted(rows)]


class NotificationTransport(Protocol):
    def enqueue(self, session: Session, event: DomainEvent, notification: Notification) -> int: ...


class NotificationService:
    def __init__(self) -> None:
        self._transports: list[NotificationTransport] = []

    def register_transport(self, transport: NotificationTransport) -> None:
        self._transports.append(transport)

    def format_event(self, event: DomainEvent) -> Notification:
        payload = event.payload
        if event.event_type == "BudgetRunningLow":
            days = payload.get("days_left")
            days_text = "нет прогноза" if days is None else f"{float(days):.1f} дн."
            return Notification(
                "⚠️ Низкий бюджет Яндекс Директа\n"
                f"Аккаунт: {payload.get('account_name', event.aggregate_id)}\n"
                f"Баланс: {float(payload.get('balance', 0)):.2f} "
                f"{payload.get('currency', '')}\n"
                f"Прогноз: {days_text}",
                "warning",
            )
        if event.event_type == "DirectAnomalyDetected":
            return Notification(
                "🚨 Аномалия Яндекс Директа\n"
                f"Аккаунт: {payload.get('account_name', event.aggregate_id)}\n"
                f"{payload.get('metric')}: {float(payload.get('actual', 0)):.2f}, "
                f"обычно {float(payload.get('baseline', 0)):.2f}",
                "critical",
            )
        if event.event_type == "ReportGenerated":
            impressions = int(payload.get("impressions", 0))
            clicks = int(payload.get("clicks", 0))
            cost = float(payload.get("cost", 0))
            conversions = float(payload.get("conversions", 0))
            ctr = clicks / impressions * 100 if impressions else 0
            cpc = cost / clicks if clicks else 0
            cpa = cost / conversions if conversions else 0
            return Notification(
                "✅ Данные Яндекс Директа обновлены\n"
                f"Аккаунт: {payload.get('account_name', event.aggregate_id)}\n"
                f"Период: {payload.get('date_from')} — {payload.get('date_to')}\n"
                f"Показы: {impressions:,}\n"
                f"Клики: {clicks:,} · CTR: {ctr:.2f}%\n"
                f"Расход: {cost:,.2f} · CPC: {cpc:,.2f}\n"
                f"Конверсии: {conversions:.2f} · CPA: {cpa:,.2f}"
            )
        if event.event_type == "DirectSyncFailed":
            return Notification(
                "❌ Не удалось обновить Яндекс Директ\n"
                f"Аккаунт: {payload.get('account_name', event.aggregate_id)}\n"
                f"Причина: {payload.get('error', 'неизвестная ошибка')}\n\n"
                "Проверьте OAuth-токен и статус заявки на доступ к API.",
                "critical",
            )
        return Notification(f"{event.event_type}: {event.payload}")

    def dispatch_pending(self, session: Session, *, limit: int = 50) -> int:
        now = datetime.now(UTC)
        events = list(
            session.scalars(
                select(DomainEvent)
                .where(
                    DomainEvent.processed_at.is_(None),
                    DomainEvent.available_at <= now,
                )
                .order_by(DomainEvent.created_at)
                .limit(limit)
            )
        )
        dispatched = 0
        for event in events:
            notification = self.format_event(event)
            queued = sum(
                transport.enqueue(session, event, notification)
                for transport in self._transports
            )
            if queued:
                event.processed_at = now
                event.last_error = None
                dispatched += 1
            else:
                event.attempts += 1
                event.last_error = "No notification destination is configured"
                event.available_at = now + timedelta(minutes=5)
        session.commit()
        return dispatched
