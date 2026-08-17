from typing import Any

from .models import MarketOrder


def _plain(value: object) -> str:
    text = str(value or "").strip()
    for character in "*_[`]":
        text = text.replace(character, "")
    return text


def item_lines(items: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in items:
        name = _plain(item.get("offerName") or item.get("offerId") or "Товар")
        count = max(1, int(item.get("count") or 1))
        lines.append(f"• {name}" + (f" × {count}" if count > 1 else ""))
    return lines or ["• Состав заказа не указан"]


def new_order_payload(order: MarketOrder, *, picker: bool) -> dict:
    text = (
        f"🆕 **Новый заказ №{order.market_order_id}**\n"
        + "\n".join(item_lines(order.items))
    )
    payload: dict = {"text": text, "format": "markdown", "notify": True}
    if picker:
        payload["attachments"] = [
            {
                "type": "inline_keyboard",
                "payload": {
                    "buttons": [
                        [
                            {
                                "type": "callback",
                                "text": "📦 Запаковал",
                                "payload": f"market.pack:{order.id}",
                            }
                        ]
                    ]
                },
            }
        ]
    return payload


def orders_payload(orders: list[MarketOrder], *, can_pack: bool) -> dict:
    if not orders:
        return {
            "text": "✅ Заказов, ожидающих упаковки, сейчас нет.",
            "format": "markdown",
            "notify": False,
        }
    lines = [f"📦 **К упаковке: {len(orders)}**"]
    for order in orders[:20]:
        lines.append(f"\n**№{order.market_order_id}**")
        lines.extend(item_lines(order.items))
    payload: dict = {
        "text": "\n".join(lines)[:4000],
        "format": "markdown",
        "notify": False,
    }
    if can_pack:
        payload["attachments"] = [
            {
                "type": "inline_keyboard",
                "payload": {
                    "buttons": [
                        [
                            {
                                "type": "callback",
                                "text": f"📦 Запаковал №{order.market_order_id}",
                                "payload": f"market.pack:{order.id}",
                            }
                        ]
                        for order in orders[:20]
                    ]
                },
            }
        ]
    return payload


def pack_queued_payload(order: MarketOrder) -> dict:
    return {
        "text": (
            f"⏳ Заказ №{order.market_order_id} принят. "
            "Передаю в Яндекс Маркет статус «Готов к отправке»."
        ),
        "format": "markdown",
        "notify": False,
    }


def packed_payload(order: MarketOrder, *, admin: bool) -> dict:
    if admin:
        text = (
            f"✅ **Заказ №{order.market_order_id} запакован**\n"
            f"Сборщик: {_plain(order.pack_requested_name or order.pack_requested_by)}\n"
            "Статус Яндекс Маркета: READY_TO_SHIP"
        )
    else:
        text = (
            f"✅ Заказ №{order.market_order_id} отмечен в Яндекс Маркете "
            "как готовый к отправке."
        )
    return {"text": text, "format": "markdown", "notify": True}


def pack_failed_payload(order: MarketOrder, *, admin: bool) -> dict:
    audience = "Администратору нужно проверить интеграцию." if admin else "Попробуйте ещё раз."
    return {
        "text": (
            f"❌ Не удалось обновить заказ №{order.market_order_id} "
            f"в Яндекс Маркете. {audience}"
        ),
        "format": "markdown",
        "notify": True,
    }
