from ....core.modules import ModuleContext, RouterModule
from ...notifications.service import InteractionRegistry
from .router import router
from .service import YandexMarketService


class YandexMarketModule(RouterModule):
    def __init__(self) -> None:
        super().__init__(
            "yandex_market",
            router,
            dependencies=("auth", "notifications"),
        )

    def configure(self, context: ModuleContext) -> None:
        service = YandexMarketService()
        context.services.add(YandexMarketService, service)
        interactions = context.services.get(InteractionRegistry)
        interactions.register(
            "market.shipment_plan",
            "📋 Что отправить",
            service.shipment_plan_notification,
            row=5,
        )
        interactions.register(
            "market.orders", "📦 Заказы к сборке", service.orders_notification, row=10
        )
        interactions.register(
            "market.status", "📊 Состояние", service.status_notification, row=20
        )
