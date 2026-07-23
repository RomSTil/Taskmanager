from .core.modules import ApplicationModule, ModuleContext, RouterModule
from .modules.event_bus import EventBusModule
from .modules.integrations.max_bot import MaxBotModule
from .modules.integrations.yandex_direct import YandexDirectModule
from .modules.notifications import NotificationsModule
from .routers import auth, notes, telegram, work
from .services.auth import LoginRateLimiter


class AuthModule(RouterModule):
    def __init__(self) -> None:
        super().__init__("auth", auth.router)

    def configure(self, context: ModuleContext) -> None:
        context.services.add(
            LoginRateLimiter,
            LoginRateLimiter(
                attempts=context.settings.login_max_attempts,
                window_seconds=context.settings.login_window_seconds,
            ),
        )


def default_modules() -> tuple[ApplicationModule, ...]:
    return (
        EventBusModule(),
        NotificationsModule(),
        AuthModule(),
        RouterModule("work", work.router, dependencies=("auth",)),
        RouterModule("knowledge", notes.router, dependencies=("auth",)),
        YandexDirectModule(),
        MaxBotModule(),
        RouterModule("telegram", telegram.router, dependencies=("auth", "work")),
    )
