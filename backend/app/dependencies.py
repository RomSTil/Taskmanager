from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, SecurityScopes
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_session
from .models import AuthToken, TokenKind, User
from .security import decode_access_token, hash_token


bearer = HTTPBearer(auto_error=False)


def _is_expired(value: datetime | None) -> bool:
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value < datetime.now(UTC)


@dataclass
class Principal:
    user: User
    scopes: set[str]
    api_token: AuthToken | None = None


def get_principal(
    security_scopes: SecurityScopes,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[Session, Depends(get_session)],
) -> Principal:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    raw = credentials.credentials
    if raw.startswith("tm_") and not raw.startswith("tmr_"):
        auth_token = session.scalar(
            select(AuthToken).where(
                AuthToken.kind == TokenKind.api,
                AuthToken.token_hash == hash_token(raw),
                AuthToken.revoked_at.is_(None),
            )
        )
        if not auth_token or _is_expired(auth_token.expires_at):
            raise HTTPException(status_code=401, detail="Invalid API token")
        user = session.get(User, auth_token.user_id)
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="Inactive owner account")
        token_scopes = set(auth_token.scopes)
        missing = set(security_scopes.scopes) - token_scopes
        if missing and "*" not in token_scopes:
            raise HTTPException(status_code=403, detail=f"Missing scopes: {', '.join(sorted(missing))}")
        auth_token.last_used_at = datetime.now(UTC)
        session.commit()
        return Principal(user=user, scopes=token_scopes, api_token=auth_token)
    try:
        user_id = decode_access_token(raw)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid access token") from exc
    user = session.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Inactive owner account")
    return Principal(user=user, scopes={"*"})


CurrentPrincipal = Annotated[Principal, Security(get_principal)]
