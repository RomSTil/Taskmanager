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
from .client import MaxApiClient
from .formatter import menu_payload, notification_payload
from .models import MaxBotConfig, MaxUpdate
from .schemas import MaxBotCreate, MaxBotCreated, MaxBotRead, MaxBotUpdate
from .service import MaxBotService


router = APIRouter(tags=["max"])


def get_max_service(request: Request) -> MaxBotService:
    return request.app.state.module_context.services.get(MaxBotService)


def get_interactions(request: Request) -> InteractionRegistry:
    return request.app.state.module_context.services.get(InteractionRegistry)


def _target(update: dict[str, Any]) -> tuple[str, int, int | None] | None:
    message = update.get("message") or {}
    recipient = message.get("recipient") or {}
    sender = message.get("sender") or update.get("user") or {}
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
        client = MaxApiClient(decrypt_secret(bot.token_encrypted))
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
    if bot.allowlist and target_id not in bot.allowlist and user_id not in bot.allowlist:
        session.commit()
        return {"accepted": True}
    if bot.target_id is None and update_type in {"bot_started", "bot_added", "message_created"}:
        bot.target_type = target_type
        bot.target_id = target_id
        bot.version += 1
    text = _message_text(update).casefold()
    if update_type in {"bot_started", "bot_added"} or text in {"/start", "/menu"}:
        service.queue(session, bot, target_type, target_id, menu_payload(interactions))
    elif update_type == "message_callback":
        notification = interactions.handle(_callback_action(update), session)
        service.queue(
            session,
            bot,
            target_type,
            target_id,
            notification_payload(notification),
        )
    session.commit()
    return {"accepted": True}
