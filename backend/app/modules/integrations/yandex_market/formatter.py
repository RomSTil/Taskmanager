from datetime import UTC
from typing import Any
from zoneinfo import ZoneInfo

from .models import MarketOrder

MARKET_TIMEZONE = ZoneInfo("Europe/Moscow")


def _plain(value: object) -> str:
    text = str(value or "").strip()
    for character in "*_[`]":
        text = text.replace(character, "")
    return text


def item_lines(items: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in items:
        name = _plain(item.get("offerName") or item.get("offerId") or "Товар")
        count = _item_count(item)
        lines.append(f"• {name}" + (f" × {count}" if count > 1 else ""))
    return lines or ["• Состав заказа не указан"]


def _item_count(item: dict[str, Any]) -> int:
    try:
        return max(1, int(item.get("count") or 1))
    except (TypeError, ValueError):
        return 1


def _order_date(order: MarketOrder) -> str | None:
    value = order.market_created_at
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(MARKET_TIMEZONE).strftime("%d.%m.%Y")


def new_order_payload(order: MarketOrder, *, picker: bool) -> dict:
    lines = [f"🟡 **Яндекс Маркет — новый заказ №{order.market_order_id}**"]
    if order_date := _order_date(order):
        lines.append(f"📅 Дата заказа: **{order_date}**")
    lines.append(f"🔢 Количество штук: **{sum(_item_count(item) for item in order.items)}**")
    lines.extend(item_lines(order.items))
    text = "\n".join(lines)
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
    previous_date: str | None | object = object()
    for order in orders[:20]:
        order_date = _order_date(order)
        if order_date != previous_date:
            heading = (
                f"📅 **Заказы за {order_date}**"
                if order_date
                else "📅 **Дата заказа не указана**"
            )
            lines.append(f"\n{heading}")
            previous_date = order_date
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
