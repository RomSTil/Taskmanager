import time

from ..config import get_settings
from ..core.modules import ModuleContext, ModuleRegistry
from ..database import SessionLocal
from ..module_catalog import default_modules
from ..modules.integrations.max_bot.worker import deliver_max_messages
from ..modules.integrations.yandex_direct.service import YandexDirectService
from ..modules.integrations.yandex_direct.worker import (
    process_direct_jobs,
    schedule_due_checks,
)
from ..modules.integrations.yandex_market.service import YandexMarketService
from ..modules.integrations.yandex_market.worker import (
    process_market_pack_requests,
    sync_due_market_accounts,
)
from ..modules.notifications.service import NotificationService


def build_context() -> ModuleContext:
    context = ModuleContext(settings=get_settings())
    ModuleRegistry(default_modules()).configure(context)
    return context


def run_once(context: ModuleContext | None = None) -> dict[str, int]:
    context = context or build_context()
    direct = context.services.get(YandexDirectService)
    market = context.services.get(YandexMarketService)
    notifications = context.services.get(NotificationService)
    with SessionLocal() as session:
        scheduled = schedule_due_checks(session, direct)
        completed = process_direct_jobs(session, direct)
        market_synced = sync_due_market_accounts(session, market)
        market_packed = process_market_pack_requests(session, market)
        dispatched = notifications.dispatch_pending(session)
        delivered = deliver_max_messages(session, verify_tls=context.settings.max_api_tls_verify)
    return {
        "scheduled": scheduled,
        "completed": completed,
        "market_synced": market_synced,
        "market_packed": market_packed,
        "dispatched": dispatched,
        "delivered": delivered,
    }


def main() -> None:
    print("Taskman platform integration worker started")
    settings = get_settings()
    context = build_context()
    while True:
        run_once(context)
        time.sleep(settings.integration_poll_seconds)


if __name__ == "__main__":
    main()
