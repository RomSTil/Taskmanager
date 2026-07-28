from ...notifications.service import InteractionRegistry, Notification


def _keyboard(interactions: InteractionRegistry) -> dict:
    buttons = [
        [
            {
                "type": "callback",
                "text": action.label,
                "payload": action.action,
            }
            for action in row
        ]
        for row in interactions.menu_rows()
    ]
    return {
        "type": "inline_keyboard",
        "payload": {"buttons": buttons},
    }


def notification_payload(
    notification: Notification,
    interactions: InteractionRegistry | None = None,
) -> dict:
    payload = {
        "text": notification.text[:4000],
        "format": "markdown",
        "notify": True,
    }
    if interactions is not None:
        payload["attachments"] = [_keyboard(interactions)]
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
) -> dict:
    return {
        "text": (
            "🔐 **Запрос доступа к боту**\n"
            f"Пользователь: {display_name}\n"
            f"MAX ID: `{user_id}`\n\n"
            "Разрешить ему просмотр статистики Яндекс Директа?"
        ),
        "format": "markdown",
        "notify": True,
        "attachments": [
            {
                "type": "inline_keyboard",
                "payload": {
                    "buttons": [
                        [
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


def menu_payload(interactions: InteractionRegistry) -> dict:
    return {
        "text": (
            "📊 **Яндекс Директ**\n"
            "Выберите показатель. Бот сначала подтвердит запрос, "
            "а затем покажет последние данные сервера."
        ),
        "format": "markdown",
        "notify": True,
        "attachments": [_keyboard(interactions)],
    }
