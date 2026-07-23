from ...core.modules import ApplicationModule, ModuleContext
from .service import InteractionRegistry, NotificationService


class NotificationsModule(ApplicationModule):
    name = "notifications"
    dependencies = ("event_bus",)

    def configure(self, context: ModuleContext) -> None:
        context.services.add(InteractionRegistry, InteractionRegistry())
        context.services.add(NotificationService, NotificationService())
