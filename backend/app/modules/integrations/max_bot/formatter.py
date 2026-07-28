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
