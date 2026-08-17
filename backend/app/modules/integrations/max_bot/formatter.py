from ...notifications.service import InteractionRegistry, Notification


def _keyboard(interactions: InteractionRegistry, prefix: str | None = None) -> dict:
    buttons = [
        [
            {
                "type": "callback",
                "text": action.label,
                "payload": action.action,
            }
            for action in row
        ]
        for row in interactions.menu_rows(prefix)
    ]
    return {
        "type": "inline_keyboard",
        "payload": {"buttons": buttons},
    }


def notification_payload(
    notification: Notification,
    interactions: InteractionRegistry | None = None,
    *,
    menu_prefix: str | None = None,
) -> dict:
    payload = {
        "text": notification.text[:4000],
        "format": "markdown",
        "notify": True,
    }
    if interactions is not None:
        payload["attachments"] = [_keyboard(interactions, menu_prefix)]
    return payload


def waiting_payload(action_label: str) -> dict:
    return {
        "text": f"⏳ Запрашиваю: {action_label}\nПожалуйста, подождите ответа сервера…",
        "format": "markdown",
        "notify": False,
    }


def access_request_payload(
    request_id: str,
    *,
    display_name: str,
    user_id: int,
    integration: str = "direct",
) -> dict:
    if integration == "market":
        question = "Какую роль выдать пользователю?"
        buttons = [
            {
                "type": "callback",
                "text": "📦 Сборщик",
                "payload": f"max.access.approve_picker:{request_id}",
            },
            {
                "type": "callback",
                "text": "👑 Админ",
                "payload": f"max.access.approve_admin:{request_id}",
            },
            {
                "type": "callback",
                "text": "❌ Отклонить",
                "payload": f"max.access.deny:{request_id}",
            },
        ]
    else:
        question = "Разрешить ему просмотр статистики Яндекс Директа?"
        buttons = [
            {
                "type": "callback",
                "text": "✅ Принять",
                "payload": f"max.access.approve:{request_id}",
            },
            {
                "type": "callback",
                "text": "❌ Отклонить",
                "payload": f"max.access.deny:{request_id}",
            },
        ]
    return {
        "text": (
            "🔐 **Запрос доступа к боту**\n"
            f"Пользователь: {display_name}\n"
            f"MAX ID: `{user_id}`\n\n"
            f"{question}"
        ),
        "format": "markdown",
        "notify": True,
        "attachments": [
            {
                "type": "inline_keyboard",
                "payload": {
                    "buttons": [
                        buttons
                    ]
                },
            }
        ],
    }


def access_pending_payload() -> dict:
    return {
        "text": (
            "⏳ **Доступ ожидает подтверждения**\n"
            "Заявка отправлена владельцу бота. "
            "После решения я пришлю отдельное сообщение."
        ),
        "format": "markdown",
        "notify": True,
    }


def access_denied_payload() -> dict:
    return {
        "text": "⛔ Владелец бота не одобрил доступ.",
        "format": "markdown",
        "notify": True,
    }


def menu_payload(interactions: InteractionRegistry, integration: str = "direct") -> dict:
    if integration == "market":
        title = "📦 **Яндекс Маркет**"
        description = "Здесь можно посмотреть очередь заказов и состояние упаковки."
    else:
        title = "📊 **Яндекс Директ**"
        description = (
            "Выберите показатель. Бот сначала подтвердит запрос, "
            "а затем покажет последние данные сервера."
        )
    return {
        "text": f"{title}\n{description}",
        "format": "markdown",
        "notify": True,
        "attachments": [_keyboard(interactions, integration)],
    }
