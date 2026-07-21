import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Security, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..config import get_settings
from ..database import get_session
from ..dependencies import Principal, get_principal
from ..models import BotConfig, ChecklistItem, Comment, OutboxMessage, Project, Task, TaskStatus, TelegramUpdate
from ..schemas import BotCreate, BotCreated, BotRead, BotUpdate
from ..security import decrypt_secret, encrypt_secret, hash_token, new_webhook_secret
from ..services.vault import note_default_path, write_note


router = APIRouter(tags=["telegram"])

ACTION_WORDS = ("написать", "позвонить", "уточнить", "сделать", "проверить", "напомнить", "взвесить", "скинуть", "спросить", "узнать")
NOTE_WORDS = ("нельзя", "можно", "помни", "важно", "правило")
WEEKDAYS = {"понедельник": 0, "вторник": 1, "среду": 2, "среда": 2, "четверг": 3, "пятницу": 4, "пятница": 4, "субботу": 5, "суббота": 5, "воскресенье": 6}
PHONE_RE = re.compile(r"(?:\+7|8)[\s()\-]*\d(?:[\s()\-]*\d){9}")


def _deadline_from_text(text: str) -> datetime | None:
    lowered = text.casefold()
    today = datetime.now(UTC).date()
    if "завтра" in lowered:
        return datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    for word, weekday in WEEKDAYS.items():
        if re.search(rf"\b{word}\b", lowered):
            days = (weekday - today.weekday()) % 7 or 7
            return datetime.combine(today + timedelta(days=days), datetime.min.time(), tzinfo=UTC)
    return None


def _steps_from_text(text: str) -> list[str]:
    matches = list(re.finditer(r"\b(?:" + "|".join(ACTION_WORDS) + r")\b", text, flags=re.IGNORECASE))
    if len(matches) < 2:
        return []
    steps: list[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        step = text[match.start():end].strip(" ,.;:-")
        step = re.sub(r"\s+(?:и|потом)\s*$", "", step, flags=re.IGNORECASE)
        if step and step.casefold() not in {item.casefold() for item in steps}:
            steps.append(step[:500])
    return steps


def _message_kind(text: str) -> str:
    lowered = text.casefold()
    if re.fullmatch(r"[\d\s.,]+", text):
        return "clarify"
    if lowered.startswith("задача:"):
        return "task"
    if lowered.startswith("заметка:"):
        return "note"
    if lowered.startswith("контакт:"):
        return "contact"
    if PHONE_RE.search(text):
        return "contact"
    if lowered.startswith("подскажите") or "как происходит процесс" in lowered:
        return "template"
    if any(word in lowered for word in NOTE_WORDS):
        return "note"
    if any(re.search(rf"\b{word}\b", lowered) for word in ACTION_WORDS) or _deadline_from_text(text):
        return "task"
    if re.match(r"^с\s+(?:вб|ozon|озон|яндекс|yandex)\b", lowered):
        return "note"
    return "task"


def _bot(session: Session, bot_id: str) -> BotConfig:
    bot = session.get(BotConfig, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Telegram bot not found")
    return bot


def _read(bot: BotConfig) -> BotRead:
    return BotRead(
        id=bot.id,
        name=bot.name,
        project_id=bot.project_id,
        token_hint=bot.token_hint,
        allowlist=bot.allowlist,
        enabled=bot.enabled,
        last_error=bot.last_error,
        version=bot.version,
        webhook_url=f"{get_settings().public_url.rstrip('/')}/api/v1/webhooks/telegram/{bot.id}",
        created_at=bot.created_at,
        updated_at=bot.updated_at,
    )


def _find_task(session: Session, reference: str) -> Task | None:
    reference = reference.strip().upper()
    if "-" in reference:
        key, _, suffix = reference.rpartition("-")
        if suffix.isdigit():
            return session.scalar(
                select(Task)
                .join(Project, Project.id == Task.project_id)
                .options(selectinload(Task.project))
                .where(Project.key == key, Task.sequence == int(suffix))
            )
    return session.scalar(select(Task).where(Task.id.like(f"{reference.lower()}%")))


def _queue(session: Session, bot: BotConfig, chat_id: int, text: str, reply_markup: dict | None = None) -> None:
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    session.add(OutboxMessage(bot_id=bot.id, chat_id=chat_id, payload=payload))


def _task_buttons(task: Task) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "В работу", "callback_data": f"status:{task.id}:in_progress"},
                {"text": "Готово", "callback_data": f"status:{task.id}:done"},
            ],
            [{"text": "Заблокировано", "callback_data": f"status:{task.id}:blocked"}],
        ]
    }


def _create_ticket(session: Session, bot: BotConfig, chat_id: int, text: str, message: dict[str, Any]) -> Task:
    sequence = None
    if bot.project_id:
        from sqlalchemy import func

        session.execute(select(Project.id).where(Project.id == bot.project_id).with_for_update())
        sequence = (session.scalar(select(func.max(Task.sequence)).where(Task.project_id == bot.project_id)) or 0) + 1
    task = Task(
        project_id=bot.project_id,
        sequence=sequence,
        title=text.splitlines()[0][:300],
        description_markdown=text,
        status=TaskStatus.inbox,
        due_at=_deadline_from_text(text),
        tags=["telegram"],
        source="telegram",
        source_data={
            "bot_id": bot.id,
            "chat_id": chat_id,
            "message_id": message.get("message_id"),
            "username": message.get("from", {}).get("username"),
        },
    )
    session.add(task)
    session.flush()
    for position, step in enumerate(_steps_from_text(text)):
        session.add(ChecklistItem(task_id=task.id, text=step, position=position))
    return task


def _create_note(session: Session, bot: BotConfig, text: str, message: dict[str, Any], kind: str) -> str:
    project = session.get(Project, bot.project_id) if bot.project_id else None
    title = text.splitlines()[0][:240]
    tags = ["telegram", kind]
    note, _ = write_note(
        session,
        title=title,
        path=note_default_path(f"TG-{message.get('message_id', 'note')}-{title}", project.key if project else None),
        content=text,
        project_id=bot.project_id,
        tags=tags,
        device_id="telegram",
    )
    return note.title


def _handle_message(session: Session, bot: BotConfig, message: dict[str, Any]) -> None:
    chat_id = int(message.get("chat", {}).get("id", 0))
    user_id = int(message.get("from", {}).get("id", 0))
    if not chat_id:
        return
    if bot.allowlist and chat_id not in bot.allowlist and user_id not in bot.allowlist:
        _queue(session, bot, chat_id, "Доступ к этому Taskman-боту не разрешён.")
        return
    text = (message.get("text") or message.get("caption") or "").strip()
    if not text:
        return
    command, _, argument = text.partition(" ")
    command = command.split("@")[0].lower()
    if command in {"/start", "/help"}:
        _queue(
            session,
            bot,
            chat_id,
            "<b>Taskman</b>\nОбычный текст или /new — новый тикет.\n"
            "/tasks [status], /search текст, /status ID status, /priority ID 0-3, "
            "/due ID YYYY-MM-DD, /project ID KEY, /comment ID текст",
        )
        return
    if command in {"/tasks", "/search"}:
        query = select(Task).options(selectinload(Task.project)).where(Task.archived_at.is_(None))
        if bot.project_id:
            query = query.where(Task.project_id == bot.project_id)
        if command == "/tasks" and argument in {item.value for item in TaskStatus}:
            query = query.where(Task.status == TaskStatus(argument))
        if command == "/search" and argument:
            query = query.where(Task.title.ilike(f"%{argument}%"))
        tasks = list(session.scalars(query.order_by(Task.created_at.desc()).limit(10)))
        body = "\n".join(f"• <b>{task.identifier}</b> [{task.status.value}] {task.title}" for task in tasks)
        _queue(session, bot, chat_id, body or "Задачи не найдены.")
        return
    if command in {"/status", "/priority", "/due", "/project", "/comment"}:
        reference, _, value = argument.partition(" ")
        task = _find_task(session, reference)
        if not task:
            _queue(session, bot, chat_id, "Задача не найдена.")
            return
        if command == "/status" and value in {item.value for item in TaskStatus}:
            task.status = TaskStatus(value)
            task.completed_at = datetime.now(UTC) if task.status == TaskStatus.done else None
            task.version += 1
        elif command == "/priority" and value.isdigit() and 0 <= int(value) <= 3:
            task.priority = int(value)
            task.version += 1
        elif command == "/due":
            if value.lower() in {"clear", "none", "нет"}:
                task.due_at = None
            else:
                try:
                    task.due_at = datetime.fromisoformat(value).replace(tzinfo=UTC)
                except ValueError:
                    _queue(session, bot, chat_id, "Срок нужен в формате YYYY-MM-DD или clear.")
                    return
            task.version += 1
        elif command == "/project":
            project = session.scalar(select(Project).where(Project.key == value.upper()))
            if not project:
                _queue(session, bot, chat_id, "Проект не найден.")
                return
            task.project_id = project.id
            from sqlalchemy import func

            session.execute(select(Project.id).where(Project.id == project.id).with_for_update())
            task.sequence = (session.scalar(select(func.max(Task.sequence)).where(Task.project_id == project.id)) or 0) + 1
            task.version += 1
        elif command == "/comment" and value:
            session.add(
                Comment(
                    task_id=task.id,
                    body_markdown=value,
                    source="telegram",
                    source_data={"bot_id": bot.id, "chat_id": chat_id},
                )
            )
        else:
            _queue(session, bot, chat_id, "Некорректные аргументы команды.")
            return
        _queue(session, bot, chat_id, f"Обновлено: <b>{task.identifier}</b> {task.title}", _task_buttons(task))
        return
    title = argument.strip() if command == "/new" else text
    if not title:
        _queue(session, bot, chat_id, "После /new нужен текст задачи.")
        return
    kind = "task" if command == "/new" else _message_kind(title)
    if kind == "clarify":
        _queue(
            session,
            bot,
            chat_id,
            "Не понял, что создать: задачу, заметку или контакт. Напиши, например: «задача: ...» или «заметка: ...».",
        )
        return
    if kind in {"note", "contact", "template"}:
        note_title = _create_note(session, bot, title, message, kind)
        labels = {"note": "Заметка", "contact": "Контакт", "template": "Шаблон"}
        _queue(session, bot, chat_id, f"{labels[kind]} сохранён: <b>{note_title}</b>")
        return
    task = _create_ticket(session, bot, chat_id, title, message)
    suffix = f"\nСрок: {task.due_at.date().isoformat()}" if task.due_at else ""
    if _steps_from_text(title):
        suffix += f"\nШагов: {len(_steps_from_text(title))}"
    _queue(session, bot, chat_id, f"Создана задача <b>{task.identifier}</b>\n{task.title}{suffix}", _task_buttons(task))


def _handle_callback(session: Session, bot: BotConfig, callback: dict[str, Any]) -> None:
    message = callback.get("message", {})
    chat_id = int(message.get("chat", {}).get("id", 0))
    user_id = int(callback.get("from", {}).get("id", 0))
    if bot.allowlist and chat_id not in bot.allowlist and user_id not in bot.allowlist:
        return
    parts = str(callback.get("data", "")).split(":")
    if len(parts) == 3 and parts[0] == "status" and parts[2] in {item.value for item in TaskStatus}:
        task = session.get(Task, parts[1])
        if task:
            task.status = TaskStatus(parts[2])
            task.completed_at = datetime.now(UTC) if task.status == TaskStatus.done else None
            task.version += 1
            _queue(session, bot, chat_id, f"{task.identifier}: статус → {task.status.value}")


def process_telegram_update(session: Session, bot: BotConfig, update: dict[str, Any]) -> bool:
    """Process one Telegram update once, for either a webhook or local polling."""
    update_id = int(update.get("update_id", -1))
    if update_id < 0:
        raise HTTPException(status_code=422, detail="Missing Telegram update_id")
    if session.scalar(
        select(TelegramUpdate.id).where(
            TelegramUpdate.bot_id == bot.id, TelegramUpdate.update_id == update_id
        )
    ):
        return False
    session.add(TelegramUpdate(bot_id=bot.id, update_id=update_id))
    if "message" in update:
        _handle_message(session, bot, update["message"])
    elif "callback_query" in update:
        _handle_callback(session, bot, update["callback_query"])
    return True


@router.get("/integrations/telegram/bots", response_model=list[BotRead])
def list_bots(
    _: Annotated[Principal, Security(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> list[BotRead]:
    return [_read(bot) for bot in session.scalars(select(BotConfig).order_by(BotConfig.name))]


@router.post("/integrations/telegram/bots", response_model=BotCreated, status_code=201)
def create_bot(
    payload: BotCreate,
    _: Annotated[Principal, Security(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> BotCreated:
    if payload.project_id and not session.get(Project, payload.project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    secret = new_webhook_secret()
    bot = BotConfig(
        name=payload.name,
        project_id=payload.project_id,
        token_encrypted=encrypt_secret(payload.token),
        token_hint=f"…{payload.token[-6:]}",
        webhook_secret_hash=hash_token(secret),
        webhook_secret_encrypted=encrypt_secret(secret),
        allowlist=payload.allowlist,
        enabled=payload.enabled,
    )
    session.add(bot)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Bot name already exists") from exc
    session.refresh(bot)
    return BotCreated(**_read(bot).model_dump(), webhook_secret=secret)


@router.patch("/integrations/telegram/bots/{bot_id}", response_model=BotRead)
def update_bot(
    bot_id: str,
    payload: BotUpdate,
    _: Annotated[Principal, Security(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> BotRead:
    bot = _bot(session, bot_id)
    if bot.version != payload.base_version:
        raise HTTPException(status_code=409, detail={"current_version": bot.version})
    for field in ("name", "project_id", "allowlist", "enabled"):
        if field in payload.model_fields_set:
            setattr(bot, field, getattr(payload, field))
    if payload.token:
        bot.token_encrypted = encrypt_secret(payload.token)
        bot.token_hint = f"…{payload.token[-6:]}"
    bot.version += 1
    session.commit()
    session.refresh(bot)
    return _read(bot)


@router.post("/integrations/telegram/bots/{bot_id}/register-webhook")
def register_webhook(
    bot_id: str,
    _: Annotated[Principal, Security(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    bot = _bot(session, bot_id)
    secret = decrypt_secret(bot.webhook_secret_encrypted)
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{decrypt_secret(bot.token_encrypted)}/setWebhook",
            json={"url": _read(bot).webhook_url, "secret_token": secret, "allowed_updates": ["message", "callback_query"]},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(str(payload))
        bot.last_error = None
    except (httpx.HTTPError, RuntimeError) as exc:
        bot.last_error = str(exc)[:1000]
        session.commit()
        raise HTTPException(status_code=502, detail="Telegram rejected webhook registration") from exc
    session.commit()
    return {"ok": True, "webhook_url": _read(bot).webhook_url}


@router.delete("/integrations/telegram/bots/{bot_id}", status_code=204)
def delete_bot(
    bot_id: str,
    _: Annotated[Principal, Security(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> None:
    bot = _bot(session, bot_id)
    session.delete(bot)
    session.commit()


@router.post("/webhooks/telegram/{bot_id}", status_code=status.HTTP_202_ACCEPTED)
def telegram_webhook(
    bot_id: str,
    update: dict[str, Any],
    session: Annotated[Session, Depends(get_session)],
    secret: Annotated[str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = None,
) -> dict[str, bool]:
    bot = _bot(session, bot_id)
    if not secret or hash_token(secret) != bot.webhook_secret_hash or not bot.enabled:
        raise HTTPException(status_code=403, detail="Invalid Telegram webhook")
    process_telegram_update(session, bot, update)
    session.commit()
    return {"accepted": True}
