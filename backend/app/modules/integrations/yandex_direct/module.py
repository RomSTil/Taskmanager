from ....core.modules import ModuleContext, RouterModule
from ...event_bus.service import EventBusService
from ...notifications.service import InteractionRegistry
from .router import router
from .service import YandexDirectService


class YandexDirectModule(RouterModule):
    def __init__(self) -> None:
        super().__init__(
            "yandex_direct",
            router,
            dependencies=("auth", "event_bus", "notifications"),
        )

    def configure(self, context: ModuleContext) -> None:
        service = YandexDirectService(context.services.get(EventBusService))
        context.services.add(YandexDirectService, service)
        interactions = context.services.get(InteractionRegistry)
        interactions.register("direct.balance", "💰 Баланс", service.balance_notification, row=10)
        interactions.register("direct.today", "📊 Сегодня", service.today_notification, row=10)
        interactions.register(
            "direct.campaigns", "📈 Кампании", service.campaigns_notification, row=20
        )
        interactions.register("direct.report", "📄 Отчёт", service.report_notification, row=30)
        interactions.register("direct.alerts", "⚠️ Алерты", service.alerts_notification, row=30)
        interactions.register(
            "direct.settings", "⚙️ Настройки", service.settings_notification, row=40
        )
