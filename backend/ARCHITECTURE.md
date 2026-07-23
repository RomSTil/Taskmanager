# Архитектура backend

Backend остаётся модульным монолитом. Для Taskman это практичнее раннего перехода к
микросервисам: одна транзакция, одна схема данных и простой deployment, но функции разделены
явными границами.

## Слои

```text
FastAPI routers          HTTP, auth scopes, сериализация
        ↓
Application services    use-cases, транзакции, orchestration
        ↓
Domain/model layer       Task, Project, Note, policy/invariants
        ↓
Infrastructure           SQLAlchemy, vault, Telegram, MCP
```

`AuthService` уже следует этой схеме. Логику из `work.py`, `notes.py` и `telegram.py` следует
переносить в сервисы постепенно, сохраняя текущий `/api/v1` контракт.

## Модули

`ApplicationModule` — основная точка расширения. Модуль объявляет уникальное имя, зависимости,
роутеры, сервисы и при необходимости startup/shutdown hooks. `ModuleRegistry` проверяет
неизвестные зависимости и циклы, сортирует модули и выключает их в обратном порядке.

Минимальный модуль:

```python
from app.core.modules import ModuleContext, RouterModule

from .router import router
from .service import CalendarService


class CalendarModule(RouterModule):
    def __init__(self) -> None:
        super().__init__("calendar", router, dependencies=("auth", "work"))

    def configure(self, context: ModuleContext) -> None:
        context.services.add(CalendarService, CalendarService(context.settings))
```

Затем экземпляр добавляется в `default_modules()` в `app/module_catalog.py`. Для теста или отдельной
сборки набор модулей можно передать напрямую в `create_app(modules=[...])`.

## Правила интеграции нового модуля

1. Код модуля хранится одним пакетом: router, schemas, service, repository/integration и тесты.
2. Router не содержит бизнес-логику и не вызывает `commit`; транзакцией владеет application service.
3. Модуль не импортирует внутренние функции другого router. Общение идёт через публичный service
   protocol, событие/outbox или общий доменный интерфейс.
4. Новые таблицы добавляются отдельной Alembic-миграцией; `create_all` остаётся только удобством
   development-режима.
5. Все внешние вызовы имеют timeout, идемпотентность, retry policy и не пишут секреты в логи.
6. Новый API сразу получает scopes, ограничения размеров, optimistic locking и negative tests.
7. Долгие операции выполняются worker-ом; запрос только создаёт job/outbox record.

## Следующая рекомендуемая декомпозиция

- `WorkService` + `TaskRepository` для проектов, задач, checklist и dashboard.
- `KnowledgeService` + `VaultRepository` с журналом согласования файлов и БД.
- `IntegrationService` и transport adapters (`TelegramAdapter`, будущие Calendar/Email adapters).
- `Workspace`/`Membership`/RBAC до появления второго пользователя.
- Типизированная шина доменных событий: `TaskCreated`, `TaskCompleted`, `DeadlineChanged`.

## Реализованный integration slice

Яндекс Директ и MAX добавлены отдельными bounded context:

```text
YandexDirectModule → IntegrationJob → DomainEvent
                                         ↓
NotificationService → MaxNotificationTransport → MaxOutboxMessage
```

`EventBusModule` хранит события транзакционно в `domain_events`. `NotificationsModule` отвечает
за форматирование событий и реестр интерактивных действий. `YandexDirectModule` регистрирует
действия меню и публикует `BudgetRunningLow`, `DirectAnomalyDetected` и `ReportGenerated`.
`MaxBotModule` знает только про нейтральные уведомления и callbacks реестра.

Долгие операции исполняет `app.integrations.platform_worker`; HTTP API только создаёт
`integration_jobs`.

Такая последовательность позволяет добавлять календарь, уведомления, учёт времени или отчёты
без импортов между роутерами и без одномоментной рискованной переписи всего приложения.
