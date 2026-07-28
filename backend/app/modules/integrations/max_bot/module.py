from ....core.modules import ModuleContext, RouterModule
from ...notifications.service import InteractionRegistry, NotificationService
from .adapter import MaxNotificationTransport
from .router import router
from .service import MaxBotService


class MaxBotModule(RouterModule):
    def __init__(self) -> None:
        super().__init__(
            "max_bot",
            router,
            dependencies=("auth", "notifications"),
        )

    def configure(self, context: ModuleContext) -> None:
        context.services.add(MaxBotService, MaxBotService(context.settings))
        interactions = context.services.get(InteractionRegistry)
        context.services.get(NotificationService).register_transport(
            MaxNotificationTransport(interactions)
        )
