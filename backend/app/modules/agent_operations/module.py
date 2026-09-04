from ...core.modules import ModuleContext, RouterModule
from .router import router
from .service import AgentOperationsService


class AgentOperationsModule(RouterModule):
    def __init__(self) -> None:
        super().__init__(
            "agent_operations",
            router,
            dependencies=("auth", "work", "knowledge", "event_bus", "notifications", "max_bot"),
        )

    def configure(self, context: ModuleContext) -> None:
        context.services.add(AgentOperationsService, AgentOperationsService(context.settings))
