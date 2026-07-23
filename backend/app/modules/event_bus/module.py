from ...core.modules import ApplicationModule, ModuleContext
from .service import EventBusService


class EventBusModule(ApplicationModule):
    name = "event_bus"

    def configure(self, context: ModuleContext) -> None:
        context.services.add(EventBusService, EventBusService())
