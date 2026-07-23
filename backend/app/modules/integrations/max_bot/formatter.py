from ...notifications.service import InteractionRegistry, Notification


def notification_payload(notification: Notification) -> dict:
    return {"text": notification.text[:4000], "format": "markdown", "notify": True}


def menu_payload(interactions: InteractionRegistry) -> dict:
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
        "text": "Яндекс Директ",
        "format": "markdown",
        "notify": True,
        "attachments": [
            {
                "type": "inline_keyboard",
                "payload": {"buttons": buttons},
            }
        ],
    }
