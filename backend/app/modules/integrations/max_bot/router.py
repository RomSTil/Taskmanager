import hashlib
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Security
from sqlalchemy import select
from sqlalchemy.orm import Session

from ....database import get_session
from ....dependencies import Principal, get_principal
from ....security import constant_time_equal, decrypt_secret, hash_token
from ...notifications.service import InteractionRegistry
from ..yandex_market.service import YandexMarketService
from .client import MaxApiClient
from .formatter import (
    access_denied_payload,
    access_pending_payload,
    access_request_payload,
    menu_payload,
    notification_payload,
    waiting_payload,
)
from .models import MaxAccessRequest, MaxBotConfig, MaxUpdate
from .schemas import (
    MaxAccessRequestRead,
    MaxAccessRequestUpdate,
    MaxBotCreate,
    MaxBotCreated,
    MaxBotRead,
    MaxBotUpdate,
)
from .service import MaxBotService

router = APIRouter(tags=["max"])


def get_max_service(request: Request) -> MaxBotService:
    return request.app.state.module_context.services.get(MaxBotService)


def get_interactions(request: Request) -> InteractionRegistry:
    return request.app.state.module_context.services.get(InteractionRegistry)


def _target(update: dict[str, Any]) -> tuple[str, int, int | None] | None:
    message = update.get("message") or {}
    recipient = message.get("recipient") or {}
    callback = update.get("callback") or {}
    sender = message.get("sender") or update.get("user") or callback.get("user") or {}
    chat_id = update.get("chat_id") or recipient.get("chat_id")
    user_id = sender.get("user_id") or update.get("user_id")
    if chat_id:
        return "chat", int(chat_id), int(user_id) if user_id else None
    if user_id:
        return "user", int(user_id), int(user_id)
    return None


def _message_text(update: dict[str, Any]) -> str:
    message = update.get("message") or {}
    body = message.get("body") or {}
    return str(body.get("text") or message.get("text") or "").strip()


def _callback_action(update: dict[str, Any]) -> str:
    callback = update.get("callback") or {}
    return str(callback.get("payload") or "").strip()


def _callback_id(update: dict[str, Any]) -> str:
    callback = update.get("callback") or {}
    return str(callback.get("callback_id") or "").strip()


def _sender_name(update: dict[str, Any], user_id: int) -> str:
    message = update.get("message") or {}
    callback = update.get("callback") or {}
    sender = message.get("sender") or update.get("user") or callback.get("user") or {}
    return str(
        sender.get("name")
        or sender.get("username")
        or sender.get("first_name")
        or f"Пользователь {user_id}"
    ).strip()[:160]


def _moderation_action(action: str) -> tuple[str, str | None, str] | None:
    prefix, separator, request_id = action.partition(":")
    if not separator or not request_id:
        return None
    if prefix == "max.access.approve":
        return "approved", "viewer", request_id
    if prefix == "max.access.approve_picker":
        return "approved", "picker", request_id
    if prefix == "max.access.approve_admin":
        return "approved", "admin", request_id
    if prefix == "max.access.deny":
        return "denied", None, request_id
    return None


COMMAND_ACTIONS = {
    "/summary": "direct.overview",
    "/today": "direct.today",
    "/week": "direct.week",
    "/month": "direct.month",
    "/campaigns": "direct.campaigns",
    "/balance": "direct.balance",
    "/alerts": "direct.alerts",
    "/refresh": "direct.refresh",
    "/settings": "direct.settings",
    "/orders": "market.orders",
}


@router.get("/integrations/max/bots", response_model=list[MaxBotRead])
def list_bots(
    _: Annotated[Principal, Security(get_principal, scopes=["integrations:manage"])],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[MaxBotService, Depends(get_max_service)],
) -> list[MaxBotRead]:
    return [
        service.read(bot)
        for bot in session.scalars(select(MaxBotConfig).order_by(MaxBotConfig.name))
    ]


@router.post("/integrations/max/bots", response_model=MaxBotCreated, status_code=201)
def create_bot(
    payload: MaxBotCreate,
    _: Annotated[Principal, Security(get_principal, scopes=["integrations:manage"])],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[MaxBotService, Depends(get_max_service)],
) -> MaxBotCreated:
    try:
        bot, secret = service.create(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return MaxBotCreated(**service.read(bot).model_dump(), webhook_secret=secret)


@router.patch("/integrations/max/bots/{bot_id}", response_model=MaxBotRead)
def update_bot(
    bot_id: str,
    payload: MaxBotUpdate,
    _: Annotated[Principal, Security(get_principal, scopes=["integrations:manage"])],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[MaxBotService, Depends(get_max_service)],
) -> MaxBotRead:
    try:
        return service.read(service.update(session, bot_id, payload))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/integrations/max/bots/{bot_id}", status_code=204)
def delete_bot(
    bot_id: str,
    _: Annotated[Principal, Security(get_principal, scopes=["integrations:manage"])],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[MaxBotService, Depends(get_max_service)],
) -> None:
    try:
        bot = service.bot(session, bot_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.delete(bot)
    session.commit()


@router.post("/integrations/max/bots/{bot_id}/register-webhook")
def register_webhook(
    bot_id: str,
    _: Annotated[Principal, Security(get_principal, scopes=["integrations:manage"])],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[MaxBotService, Depends(get_max_service)],
) -> dict[str, Any]:
    try:
        bot = service.bot(session, bot_id)
        client = MaxApiClient(
            decrypt_secret(bot.token_encrypted),
            verify_tls=service.settings.max_api_tls_verify,
        )
        result = client.register_webhook(
            service.read(bot).webhook_url,
            decrypt_secret(bot.webhook_secret_encrypted),
        )
        bot.last_error = None
        session.commit()
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        bot = session.get(MaxBotConfig, bot_id)
        if bot:
            bot.last_error = f"Webhook registration failed ({type(exc).__name__})"
            session.commit()
        raise HTTPException(status_code=502, detail="MAX rejected webhook registration") from exc


@router.get(
    "/integrations/max/bots/{bot_id}/access-requests",
    response_model=list[MaxAccessRequestRead],
)
def list_access_requests(
    bot_id: str,
    _: Annotated[Principal, Security(get_principal, scopes=["integrations:manage"])],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[MaxBotService, Depends(get_max_service)],
) -> list[MaxAccessRequest]:
    try:
        service.bot(session, bot_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return list(
        session.scalars(
            select(MaxAccessRequest)
            .where(MaxAccessRequest.bot_id == bot_id)
            .order_by(MaxAccessRequest.requested_at.desc())
        )
    )


@router.patch(
    "/integrations/max/bots/{bot_id}/access-requests/{request_id}",
    response_model=MaxAccessRequestRead,
)
def update_access_request(
    bot_id: str,
    request_id: str,
    payload: MaxAccessRequestUpdate,
    _: Annotated[Principal, Security(get_principal, scopes=["integrations:manage"])],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[MaxBotService, Depends(get_max_service)],
) -> MaxAccessRequest:
    try:
        bot = service.bot(session, bot_id)
        if bot.integration == "market" and payload.role == "viewer":
            raise ValueError("Market users must be picker or admin")
        return service.manage_access(
            session,
            bot,
            request_id,
            decision=payload.status,
            role=payload.role,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/webhooks/max/{bot_id}")
def max_webhook(
    bot_id: str,
    update: dict[str, Any],
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    secret: Annotated[str | None, Header(alias="X-Max-Bot-Api-Secret")] = None,
) -> dict[str, bool]:
    service = get_max_service(request)
    interactions = get_interactions(request)
    try:
        bot = service.bot(session, bot_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if (
        not bot.enabled
        or not secret
        or not constant_time_equal(hash_token(secret), bot.webhook_secret_hash)
    ):
        raise HTTPException(status_code=403, detail="Invalid MAX webhook")
    canonical = json.dumps(update, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    update_key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if session.scalar(
        select(MaxUpdate.id).where(
            MaxUpdate.bot_id == bot.id,
            MaxUpdate.update_key == update_key,
        )
    ):
        return {"accepted": True}
    update_type = str(update.get("update_type") or "unknown")
    session.add(
        MaxUpdate(bot_id=bot.id, update_key=update_key, update_type=update_type)
    )
    target = _target(update)
    if target is None:
        session.commit()
        return {"accepted": True}
    target_type, target_id, user_id = target
    if bot.target_id is None and update_type in {"bot_started", "bot_added", "message_created"}:
        bot.target_type = target_type
        bot.target_id = target_id
        if user_id is not None:
            service.claim_owner(session, bot, user_id)
        else:
            bot.version += 1
    elif (
        bot.owner_user_id is None
        and user_id is not None
        and bot.target_type == "chat"
        and target_type == "chat"
        and bot.target_id == target_id
    ):
        # Legacy records only stored the dialog ID, which is not a MAX user ID.
        service.claim_owner(session, bot, user_id)
    action = _callback_action(update) if update_type == "message_callback" else ""
    moderation = _moderation_action(action)
    is_owner = user_id is not None and user_id == bot.owner_user_id
    if moderation and is_owner and user_id is not None:
        decision, role, request_id = moderation
        try:
            access = service.review_access(
                session,
                bot,
                request_id,
                decision=decision,
                reviewer_id=user_id,
                role=role,
            )
        except LookupError:
            service.queue(
                session,
                bot,
                target_type,
                target_id,
                {"text": "Заявка не найдена.", "format": "markdown", "notify": True},
            )
        else:
            approved = access.status == "approved"
            applicant_payload = (
                menu_payload(interactions, bot.integration)
                if approved
                else access_denied_payload()
            )
            if approved:
                applicant_payload["text"] = (
                    "✅ **Доступ одобрен**\n"
                    + (
                        f"Ваша роль: {'Сборщик' if access.role == 'picker' else 'Админ'}.\n\n"
                        if bot.integration == "market"
                        else "Теперь вам доступна статистика Яндекс Директа.\n\n"
                    )
                    + applicant_payload["text"]
                )
            service.queue(
                session,
                bot,
                access.target_type,
                access.target_id,
                applicant_payload,
            )
            service.queue(
                session,
                bot,
                target_type,
                target_id,
                notification_payload(
                    interactions.handle("direct.settings", session),
                    interactions,
                    menu_prefix=bot.integration,
                )
                | {
                    "text": (
                        f"{'✅ Доступ разрешён' if approved else '❌ Доступ отклонён'}\n"
                        f"{access.display_name} · ID {access.user_id}"
                    )
                },
            )
        session.commit()
        return {"accepted": True}

    allowed = is_owner or service.approved_user(session, bot, user_id)
    if not allowed:
        if user_id is None:
            session.commit()
            return {"accepted": True}
        access, created = service.access_request(
            session,
            bot,
            user_id=user_id,
            display_name=_sender_name(update, user_id),
            target_type=target_type,
            target_id=target_id,
        )
        if access.status == "denied":
            service.queue(
                session,
                bot,
                target_type,
                target_id,
                access_denied_payload(),
            )
        elif access.status == "approved":
            allowed = True
        elif created:
            service.queue(
                session,
                bot,
                target_type,
                target_id,
                access_pending_payload(),
            )
            if bot.target_type and bot.target_id is not None:
                service.queue(
                    session,
                    bot,
                    bot.target_type,
                    int(bot.target_id),
                    access_request_payload(
                        access.id,
                        display_name=access.display_name,
                        user_id=access.user_id,
                        integration=bot.integration,
                    ),
                )
        if not allowed:
            session.commit()
            return {"accepted": True}
    text = _message_text(update).casefold()
    if update_type in {"bot_started", "bot_added"} or text in {"/start", "/menu"}:
        service.queue(
            session,
            bot,
            target_type,
            target_id,
            menu_payload(interactions, bot.integration),
        )
    elif update_type == "message_callback":
        role = service.user_role(session, bot, user_id)
        if action.startswith("market.pack:"):
            if bot.integration != "market" or role != "picker" or user_id is None:
                service.queue(
                    session,
                    bot,
                    target_type,
                    target_id,
                    {
                        "text": "⛔ Упаковку может подтверждать только сборщик.",
                        "format": "markdown",
                        "notify": True,
                    },
                )
                session.commit()
                return {"accepted": True}
            order_id = action.partition(":")[2]
            market = request.app.state.module_context.services.get(YandexMarketService)
            try:
                order = market.request_pack(
                    session,
                    order_id,
                    user_id=user_id,
                    display_name=_sender_name(update, user_id),
                )
                payload = market.pack_request_payload(order)
            except LookupError:
                payload = {
                    "text": "Заказ не найден.",
                    "format": "markdown",
                    "notify": True,
                }
            except RuntimeError as exc:
                payload = {
                    "text": f"⚠️ {exc}",
                    "format": "markdown",
                    "notify": True,
                }
            service.queue(session, bot, target_type, target_id, payload)
            session.commit()
            return {"accepted": True}
        if action == "market.orders" and bot.integration == "market":
            market = request.app.state.module_context.services.get(YandexMarketService)
            service.queue(
                session,
                bot,
                target_type,
                target_id,
                market.orders_payload(session, can_pack=role == "picker"),
            )
            session.commit()
            return {"accepted": True}
        if not action.startswith(f"{bot.integration}."):
            service.queue(
                session,
                bot,
                target_type,
                target_id,
                {"text": "Действие недоступно для этого бота.", "notify": False},
            )
            session.commit()
            return {"accepted": True}
        wait_payload = waiting_payload(interactions.label_for(action))
        callback_answered = False
        callback_id = _callback_id(update)
        if callback_id:
            try:
                MaxApiClient(
                    decrypt_secret(bot.token_encrypted),
                    verify_tls=service.settings.max_api_tls_verify,
                ).answer_callback(callback_id, wait_payload)
                callback_answered = True
            except Exception:  # noqa: BLE001
                # The result still goes through the durable outbox if MAX cannot
                # acknowledge the callback immediately.
                callback_answered = False
        if not callback_answered:
            service.queue(session, bot, target_type, target_id, wait_payload)
        notification = interactions.handle(action, session)
        service.queue(
            session,
            bot,
            target_type,
            target_id,
            notification_payload(
                notification,
                interactions,
                menu_prefix=bot.integration,
            ),
        )
    elif text in COMMAND_ACTIONS:
        action = COMMAND_ACTIONS[text]
        if not action.startswith(f"{bot.integration}."):
            session.commit()
            return {"accepted": True}
        if action == "market.orders":
            market = request.app.state.module_context.services.get(YandexMarketService)
            service.queue(
                session,
                bot,
                target_type,
                target_id,
                market.orders_payload(
                    session,
                    can_pack=service.user_role(session, bot, user_id) == "picker",
                ),
            )
            session.commit()
            return {"accepted": True}
        service.queue(
            session,
            bot,
            target_type,
            target_id,
            notification_payload(
                interactions.handle(action, session),
                interactions,
                menu_prefix=bot.integration,
            ),
        )
    session.commit()
    return {"accepted": True}
