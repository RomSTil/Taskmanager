# Заказы Яндекс Маркета в MAX

Модуль получает FBS-заказы Яндекс Маркета, сохраняет рабочее состояние в PostgreSQL и
доставляет ролевые уведомления через отдельного MAX-бота.

## Роли

- `picker` (сборщик) видит количество заказов, карточки товаров и кнопку «Запаковал»;
- `admin` видит новые заказы и получает сообщение о том, какой сборщик закончил упаковку;
- первый пользователь, запустивший непривязанный бот, становится владельцем и администратором;
- новые пользователи создают заявку. Владелец выбирает роль «Сборщик», «Админ» или отклоняет её.

MAX ID, имя, статус заявки и назначенная роль хранятся в таблице
`max_access_requests`. API-Key Маркета и токен MAX хранятся только в зашифрованном виде.

## Подключение

Создайте аккаунт Маркета через защищённый Taskman API:

```http
POST /api/v1/integrations/yandex-market/accounts
Authorization: Bearer <taskman-access-token>
Content-Type: application/json

{
  "name": "Основной магазин",
  "campaign_id": 149086260,
  "api_key": "<yandex-market-api-key>",
  "poll_interval_seconds": 60
}
```

Создайте отдельную конфигурацию MAX-бота. `target_type` и `target_id` можно не указывать:
владелец будет определён по первому `/start`.

```http
POST /api/v1/integrations/max/bots
Authorization: Bearer <taskman-access-token>
Content-Type: application/json

{
  "name": "Market packing",
  "token": "<max-bot-token>",
  "integration": "market"
}
```

Ответ содержит одноразовый `webhook_secret`. Затем зарегистрируйте webhook:

```http
POST /api/v1/integrations/max/bots/<bot-id>/register-webhook
Authorization: Bearer <taskman-access-token>
```

Публичный URL должен работать по HTTPS на порту 443. Для MAX в окружении должен быть
доступен доверенный корневой сертификат, требуемый платформой MAX; отключать TLS-проверку в
production нельзя.

## Обработка заказов

`platform-worker` раз в минуту запрашивает заказы `PROCESSING/STARTED`. Новый заказ создаётся
в `market_orders` только один раз и рассылается всем пользователям Market-бота согласно роли.

После нажатия «Запаковал» webhook фиксирует заявку в PostgreSQL. Фоновый worker выполняет:

```http
PUT /v2/campaigns/{campaignId}/orders/{orderId}/status

{
  "order": {
    "status": "PROCESSING",
    "substatus": "READY_TO_SHIP"
  }
}
```

До успешного ответа Яндекс Маркета заказ не считается запакованным. Повторные webhook-события
дедуплицируются, а конкурентная обработка одного заказа блокируется на уровне PostgreSQL.
