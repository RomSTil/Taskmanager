from datetime import UTC
from decimal import Decimal, InvalidOperation
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


def _shipment_date(order: MarketOrder) -> str | None:
    return order.shipment_date.strftime("%d.%m.%Y") if order.shipment_date else None


def _order_total(order: MarketOrder) -> Decimal:
    total = Decimal("0")
    for item in order.items:
        try:
            price = Decimal(str(item.get("buyerPrice") or item.get("price") or "0"))
        except (InvalidOperation, ValueError):
            price = Decimal("0")
        total += price * _item_count(item)
    return total


def _delivery_status(order: MarketOrder) -> str:
    substatus_labels = {
        "STARTED": "Ожидает сборки",
        "READY_TO_SHIP": "Ожидает отгрузки",
        "SHIPPED": "Передан в доставку",
    }
    status_labels = {
        "PENDING": "В обработке",
        "PROCESSING": "В обработке",
        "DELIVERY": "Доставляется",
        "PICKUP": "В пункте выдачи",
        "DELIVERED": "Доставлен",
        "CANCELLED": "Отменён",
        "UNPAID": "Ожидает оплаты",
        "RESERVED": "Зарезервирован",
        "PARTIALLY_RETURNED": "Частично возвращён",
        "RETURNED": "Возвращён",
    }
    return substatus_labels.get(
        order.substatus or "",
        status_labels.get(order.status, _plain(order.substatus or order.status or "Неизвестно")),
    )


def _order_lines(order: MarketOrder, *, new: bool = False) -> list[str]:
    qualifier = "новый заказ" if new else "заказ"
    lines = [f"🟡 **Яндекс Маркет — {qualifier} №{order.market_order_id}**"]
    if order_date := _order_date(order):
        lines.append(f"📅 Дата заказа: **{order_date}**")
    lines.append(
        f"🔢 Количество штук: **{sum(_item_count(item) for item in order.items)}**"
    )
    lines.extend(item_lines(order.items))
    if shipment_date := _shipment_date(order):
        lines.append(f"⏰ Отгрузить до: **{shipment_date}**")
    lines.append(
        f"🚚 Статус доставки: **{_delivery_status(order)}** · "
        f"💰 **{_order_total(order):.2f} RUB**"
    )
    return lines


def new_order_payload(order: MarketOrder, *, picker: bool) -> dict:
    text = "\n".join(_order_lines(order, new=True))
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
            "text": "📦 **Последние заказы Yandex**\nЗаказы ещё не загружены.",
            "format": "markdown",
            "notify": False,
        }
    visible_orders = orders[:10]
    lines = ["📦 **Последние заказы Yandex**"]
    for order in visible_orders:
        lines.append("")
        lines.extend(_order_lines(order))
    payload: dict = {
        "text": "\n".join(lines)[:4000],
        "format": "markdown",
        "notify": False,
    }
    packable_orders = [
        order
        for order in visible_orders
        if order.status == "PROCESSING"
        and order.substatus == "STARTED"
        and order.pack_state in {"available", "failed"}
    ]
    if can_pack and packable_orders:
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
                        for order in packable_orders
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
    provider_status = order.substatus or order.status
    if admin:
        text = (
            f"✅ **Заказ №{order.market_order_id} запакован**\n"
            f"Сборщик: {_plain(order.pack_requested_name or order.pack_requested_by)}\n"
            f"Статус Яндекс Маркета: `{provider_status}`"
        )
    else:
        text = (
            f"✅ Заказ №{order.market_order_id} отмечен в Яндекс Маркете "
            "как готовый к отправке."
        )
    return {"text": text, "format": "markdown", "notify": True}


def pack_failed_payload(order: MarketOrder, *, admin: bool) -> dict:
    if admin and order.pack_error:
        audience = f"Причина: {_plain(order.pack_error)}"
    else:
        audience = "Попробуйте ещё раз."
    return {
        "text": (
            f"❌ Не удалось обновить заказ №{order.market_order_id} "
            f"в Яндекс Маркете. {audience}"
        ),
        "format": "markdown",
        "notify": True,
    }
