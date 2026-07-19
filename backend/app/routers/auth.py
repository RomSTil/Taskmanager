from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Security, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_session
from ..dependencies import Principal, get_principal
from ..models import AuthToken, Project, TokenKind, User
from ..schemas import (
    ApiTokenCreate,
    ApiTokenCreated,
    ApiTokenRead,
    LoginRequest,
    RefreshRequest,
    SetupRequest,
    SetupState,
    TokenPair,
    UserRead,
)
from ..security import (
    constant_time_equal,
    create_access_token,
    hash_password,
    hash_token,
    new_api_token,
    new_refresh_token,
    verify_password,
)


router = APIRouter(prefix="/auth", tags=["auth"])


def _expired(value: datetime | None) -> bool:
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value < datetime.now(UTC)


def _issue_pair(session: Session, user: User) -> TokenPair:
    access, expires_at = create_access_token(user.id)
    refresh = new_refresh_token()
    session.add(
        AuthToken(
            user_id=user.id,
            name="desktop session",
            kind=TokenKind.refresh,
            token_hash=hash_token(refresh),
            scopes=["*"],
            expires_at=datetime.now(UTC) + timedelta(days=get_settings().refresh_token_days),
        )
    )
    session.commit()
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_at=expires_at,
        user=UserRead.model_validate(user),
    )


@router.get("/setup", response_model=SetupState)
def setup_state(session: Annotated[Session, Depends(get_session)]) -> SetupState:
    return SetupState(setup_required=(session.scalar(select(func.count(User.id))) or 0) == 0)


@router.post("/setup", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
def setup(
    payload: SetupRequest,
    session: Annotated[Session, Depends(get_session)],
    setup_token: Annotated[str | None, Header(alias="X-Setup-Token")] = None,
) -> TokenPair:
    if (session.scalar(select(func.count(User.id))) or 0) > 0:
        raise HTTPException(status_code=409, detail="Owner account already exists")
    required_token = get_settings().setup_token
    if required_token and (not setup_token or not constant_time_equal(setup_token, required_token)):
        raise HTTPException(status_code=403, detail="Invalid setup token")
    user = User(username=payload.username.strip(), password_hash=hash_password(payload.password))
    session.add(user)
    session.flush()
    session.add(
        Project(
            name="Личное пространство",
            key="HOME",
            description="Общие задачи и заметки до распределения по проектам.",
            color="#8b5cf6",
        )
    )
    session.commit()
    session.refresh(user)
    return _issue_pair(session, user)


@router.post("/login", response_model=TokenPair)
def login(payload: LoginRequest, session: Annotated[Session, Depends(get_session)]) -> TokenPair:
    user = session.scalar(select(User).where(User.username == payload.username.strip()))
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return _issue_pair(session, user)


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: RefreshRequest, session: Annotated[Session, Depends(get_session)]) -> TokenPair:
    token = session.scalar(
        select(AuthToken).where(
            AuthToken.kind == TokenKind.refresh,
            AuthToken.token_hash == hash_token(payload.refresh_token),
            AuthToken.revoked_at.is_(None),
        )
    )
    if not token or _expired(token.expires_at):
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    user = session.get(User, token.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Inactive owner account")
    token.revoked_at = datetime.now(UTC)
    session.commit()
    return _issue_pair(session, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: RefreshRequest, session: Annotated[Session, Depends(get_session)]) -> None:
    token = session.scalar(select(AuthToken).where(AuthToken.token_hash == hash_token(payload.refresh_token)))
    if token and token.revoked_at is None:
        token.revoked_at = datetime.now(UTC)
        session.commit()


@router.get("/me", response_model=UserRead)
def me(principal: Annotated[Principal, Security(get_principal)]) -> User:
    return principal.user


@router.get("/tokens", response_model=list[ApiTokenRead])
def list_tokens(
    _: Annotated[Principal, Security(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> list[AuthToken]:
    return list(
        session.scalars(
            select(AuthToken)
            .where(AuthToken.kind == TokenKind.api)
            .order_by(AuthToken.created_at.desc())
        )
    )


@router.post("/tokens", response_model=ApiTokenCreated, status_code=status.HTTP_201_CREATED)
def create_api_token(
    payload: ApiTokenCreate,
    principal: Annotated[Principal, Security(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> ApiTokenCreated:
    allowed = {"projects:read", "projects:write", "tasks:read", "tasks:write", "notes:read", "notes:write"}
    if not set(payload.scopes).issubset(allowed):
        raise HTTPException(status_code=422, detail="Unknown API token scope")
    raw = new_api_token()
    token = AuthToken(
        user_id=principal.user.id,
        name=payload.name,
        kind=TokenKind.api,
        token_hash=hash_token(raw),
        scopes=payload.scopes,
        expires_at=payload.expires_at,
    )
    session.add(token)
    session.commit()
    session.refresh(token)
    return ApiTokenCreated(**ApiTokenRead.model_validate(token).model_dump(), token=raw)


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_api_token(
    token_id: str,
    _: Annotated[Principal, Security(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> None:
    token = session.get(AuthToken, token_id)
    if not token or token.kind != TokenKind.api:
        raise HTTPException(status_code=404, detail="API token not found")
    token.revoked_at = datetime.now(UTC)
    session.commit()
