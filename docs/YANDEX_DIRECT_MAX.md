# Яндекс Директ и MAX

Интеграция построена как независимые модули:

```text
YandexDirectModule
    └── IntegrationJob → YandexDirectWorker
                              └── DomainEvent
                                      └── NotificationService
                                              └── MaxNotificationTransport
                                                      └── MaxOutboxMessage
```

`MaxBotModule` не импортирует модели или клиент Яндекс Директа. Меню собирается через
`InteractionRegistry`: provider регистрирует действия, а транспорт только отображает кнопки и
передаёт callback обратно в реестр.

## Настройка

Реальные токены не должны храниться в Git. Они передаются через защищённые API Taskman и
сохраняются в БД в зашифрованном виде.

Добавить аккаунт Яндекс Директа:

```http
POST /api/v1/integrations/yandex-direct/accounts
Authorization: Bearer <taskman-access-token>
Content-Type: application/json

{
  "name": "Основной кабинет",
  "token": "<yandex-oauth-token>",
  "balance_threshold": 5000,
  "days_left_threshold": 3,
  "monitor_interval_minutes": 30
}
```

Для агентского аккаунта укажите `client_login`.

Добавить MAX-бота:

```http
POST /api/v1/integrations/max/bots
Authorization: Bearer <taskman-access-token>
Content-Type: application/json

{
  "name": "Direct alerts",
  "token": "<max-bot-token>",
  "allowlist": [123456789]
}
```

Ответ содержит одноразовый `webhook_secret`. После этого зарегистрируйте webhook:

```http
POST /api/v1/integrations/max/bots/<bot-id>/register-webhook
Authorization: Bearer <taskman-access-token>
```

Production URL Taskman должен использовать HTTPS на порту 443. MAX отправляет секрет в
`X-Max-Bot-Api-Secret`; Taskman проверяет этот заголовок и дедуплицирует webhook-события.

## Jobs и мониторинг

HTTP-запрос не обращается к Директу синхронно. Он создаёт job:

```http
POST /api/v1/integrations/yandex-direct/accounts/<account-id>/jobs
Authorization: Bearer <taskman-access-token>
Content-Type: application/json

{"job_type": "balance_check"}
```

Поддерживаются:

- `balance_check` — кампании, статистика, прогноз остатка и аномалии;
- `campaign_sync` — обновление локального снимка кампаний;
- `report` — отчёт за выбранный период и событие `ReportGenerated`.

Статус доступен через `GET /api/v1/integrations/yandex-direct/jobs/<job-id>`.

Worker запускается командой:

```powershell
python -m app.integrations.platform_worker
```

В Docker Compose это сервис `platform-worker`. Он:

1. создаёт плановые проверки для активных аккаунтов;
2. исполняет pending jobs с повторными попытками;
3. преобразует доменные события в уведомления;
4. доставляет MAX outbox.

## Ограничение баланса

API Директа возвращает баланс кампании, когда используется отдельный счёт кампании. Для кампаний
с общим счётом поле текущего остатка недоступно этим методом. Такие кампании учитываются в
статистике и отчётах, но в ответе job отражаются как `shared_account_campaigns`.
