from ....core.modules import ModuleContext, RouterModule
from ...event_bus.service import EventBusService
from ...notifications.service import InteractionRegistry
from .router import router
from .service import OzonSellerService


class OzonSellerModule(RouterModule):
    def __init__(self) -> None:
        super().__init__(
            "ozon_seller",
            router,
            dependencies=("auth", "event_bus", "notifications"),
        )

    def configure(self, context: ModuleContext) -> None:
        service = OzonSellerService(context.services.get(EventBusService))
        context.services.add(OzonSellerService, service)
        interactions = context.services.get(InteractionRegistry)
        interactions.register(
            "market.ozon_orders",
            "📦 Ozon: заказы",
            service.recent_orders_notification,
            row=30,
        )
        interactions.register(
            "market.ozon_refresh",
            "🔄 Ozon: обновить",
            service.refresh_notification,
            row=30,
        )
