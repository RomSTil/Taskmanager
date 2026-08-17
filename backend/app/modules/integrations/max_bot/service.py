from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ....config import Settings
from ....security import encrypt_secret, hash_token, new_webhook_secret
from .models import MaxAccessRequest, MaxBotConfig, MaxOutboxMessage
from .schemas import MaxBotCreate, MaxBotRead, MaxBotUpdate


class MaxBotService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def bot(self, session: Session, bot_id: str) -> MaxBotConfig:
        bot = session.get(MaxBotConfig, bot_id)
        if bot is None:
            raise LookupError("MAX bot not found")
        return bot

    def read(self, bot: MaxBotConfig) -> MaxBotRead:
        return MaxBotRead(
            id=bot.id,
            name=bot.name,
            token_hint=bot.token_hint,
            integration=bot.integration,
            allowlist=bot.allowlist,
            target_type=bot.target_type,
            target_id=bot.target_id,
            enabled=bot.enabled,
            last_error=bot.last_error,
            version=bot.version,
            webhook_url=(
                f"{self.settings.public_url.rstrip('/')}/api/v1/webhooks/max/{bot.id}"
            ),
            created_at=bot.created_at,
            updated_at=bot.updated_at,
        )

    def create(
        self,
        session: Session,
        payload: MaxBotCreate,
    ) -> tuple[MaxBotConfig, str]:
        secret = new_webhook_secret()
        bot = MaxBotConfig(
            name=payload.name,
            token_encrypted=encrypt_secret(payload.token),
            token_hint=f"…{payload.token[-6:]}",
            webhook_secret_hash=hash_token(secret),
            webhook_secret_encrypted=encrypt_secret(secret),
            integration=payload.integration,
            allowlist=payload.allowlist,
            target_type=payload.target_type,
            target_id=payload.target_id,
            owner_user_id=payload.target_id if payload.target_type == "user" else None,
            enabled=payload.enabled,
        )
        session.add(bot)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise ValueError("MAX bot name already exists") from exc
        session.refresh(bot)
        return bot, secret

    def update(
        self,
        session: Session,
        bot_id: str,
        payload: MaxBotUpdate,
    ) -> MaxBotConfig:
        bot = self.bot(session, bot_id)
        if bot.version != payload.base_version:
            raise RuntimeError("MAX bot version conflict")
        for field in (
            "name",
            "integration",
            "allowlist",
            "target_type",
            "target_id",
            "enabled",
        ):
            if field in payload.model_fields_set:
                setattr(bot, field, getattr(payload, field))
        if payload.token:
            bot.token_encrypted = encrypt_secret(payload.token)
            bot.token_hint = f"…{payload.token[-6:]}"
        bot.version += 1
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise ValueError("MAX bot name already exists") from exc
        session.refresh(bot)
        return bot

    def queue(
        self,
        session: Session,
        bot: MaxBotConfig,
        target_type: str,
        target_id: int,
        payload: dict,
    ) -> MaxOutboxMessage:
        message = MaxOutboxMessage(
            bot_id=bot.id,
            target_type=target_type,
            target_id=target_id,
            payload=payload,
        )
        session.add(message)
        return message

    def access_request(
        self,
        session: Session,
        bot: MaxBotConfig,
        *,
        user_id: int,
        display_name: str,
        target_type: str,
        target_id: int,
    ) -> tuple[MaxAccessRequest, bool]:
        existing = session.scalar(
            select(MaxAccessRequest).where(
                MaxAccessRequest.bot_id == bot.id,
                MaxAccessRequest.user_id == user_id,
            )
        )
        if existing is not None:
            existing.display_name = display_name[:160]
            existing.target_type = target_type
            existing.target_id = target_id
            return existing, False
        request = MaxAccessRequest(
            bot_id=bot.id,
            user_id=user_id,
            display_name=display_name[:160],
            target_type=target_type,
            target_id=target_id,
        )
        session.add(request)
        session.flush()
        return request, True

    def approved_user(
        self,
        session: Session,
        bot: MaxBotConfig,
        user_id: int | None,
    ) -> bool:
        if user_id is None:
            return False
        if user_id in bot.allowlist:
            return True
        return bool(
            session.scalar(
                select(MaxAccessRequest.id).where(
                    MaxAccessRequest.bot_id == bot.id,
                    MaxAccessRequest.user_id == user_id,
                    MaxAccessRequest.status == "approved",
                )
            )
        )

    def user_role(
        self,
        session: Session,
        bot: MaxBotConfig,
        user_id: int | None,
    ) -> str | None:
        if user_id is None:
            return None
        if user_id == bot.owner_user_id:
            return "admin"
        request = session.scalar(
            select(MaxAccessRequest).where(
                MaxAccessRequest.bot_id == bot.id,
                MaxAccessRequest.user_id == user_id,
                MaxAccessRequest.status == "approved",
            )
        )
        if request is not None:
            return request.role
        if user_id in bot.allowlist:
            return "admin" if bot.integration == "market" else "viewer"
        return None

    def claim_owner(
        self,
        session: Session,
        bot: MaxBotConfig,
        user_id: int,
    ) -> None:
        bot.owner_user_id = user_id
        bot.allowlist = list(dict.fromkeys([*bot.allowlist, user_id]))
        bot.version += 1
        request = session.scalar(
            select(MaxAccessRequest).where(
                MaxAccessRequest.bot_id == bot.id,
                MaxAccessRequest.user_id == user_id,
            )
        )
        if request is not None and request.status == "pending":
            request.status = "approved"
            request.reviewed_by = user_id
            request.reviewed_at = datetime.now(UTC)

    def review_access(
        self,
        session: Session,
        bot: MaxBotConfig,
        request_id: str,
        *,
        decision: str,
        reviewer_id: int,
        role: str | None = None,
    ) -> MaxAccessRequest:
        request = session.get(MaxAccessRequest, request_id)
        if request is None or request.bot_id != bot.id:
            raise LookupError("MAX access request not found")
        if request.status != "pending":
            return request
        request.status = decision
        if decision == "approved" and role:
            request.role = role
        request.reviewed_by = reviewer_id
        request.reviewed_at = datetime.now(UTC)
        if decision == "approved":
            bot.allowlist = list(dict.fromkeys([*bot.allowlist, request.user_id]))
            bot.version += 1
        return request

    def manage_access(
        self,
        session: Session,
        bot: MaxBotConfig,
        request_id: str,
        *,
        decision: str,
        role: str | None,
    ) -> MaxAccessRequest:
        request = session.get(MaxAccessRequest, request_id)
        if request is None or request.bot_id != bot.id:
            raise LookupError("MAX access request not found")
        if decision == "approved" and role is None:
            raise ValueError("Role is required for approved access")
        request.status = decision
        if role is not None:
            request.role = role
        request.reviewed_by = bot.owner_user_id
        request.reviewed_at = datetime.now(UTC)
        allowlist = list(bot.allowlist)
        if decision == "approved" and request.user_id not in allowlist:
            allowlist.append(request.user_id)
        if decision == "denied" and request.user_id in allowlist:
            allowlist.remove(request.user_id)
        if allowlist != bot.allowlist:
            bot.allowlist = allowlist
            bot.version += 1
        session.commit()
        session.refresh(request)
        return request
