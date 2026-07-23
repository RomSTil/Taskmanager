from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Security, status
from sqlalchemy.orm import Session

from ..database import get_session
from ..dependencies import Principal, get_principal
from ..models import AuthToken, User
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
from ..services.auth import AuthService, LoginRateLimiter


router = APIRouter(prefix="/auth", tags=["auth"])


def get_auth_service(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> AuthService:
    context = request.app.state.module_context
    limiter = context.services.get(LoginRateLimiter)
    return AuthService(session, context.settings, limiter)


AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]


@router.get("/setup", response_model=SetupState)
def setup_state(service: AuthServiceDependency) -> SetupState:
    return SetupState(setup_required=service.setup_required())


@router.post("/setup", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
def setup(
    payload: SetupRequest,
    service: AuthServiceDependency,
    setup_token: Annotated[str | None, Header(alias="X-Setup-Token")] = None,
) -> TokenPair:
    return service.setup(payload, setup_token)


@router.post("/login", response_model=TokenPair)
def login(payload: LoginRequest, request: Request, service: AuthServiceDependency) -> TokenPair:
    client_host = request.client.host if request.client else "unknown"
    attempt_key = f"{client_host}:{payload.username.strip().casefold()}"
    return service.login(payload, attempt_key)


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: RefreshRequest, service: AuthServiceDependency) -> TokenPair:
    return service.refresh(payload.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: RefreshRequest, service: AuthServiceDependency) -> None:
    service.logout(payload.refresh_token)


@router.get("/me", response_model=UserRead)
def me(principal: Annotated[Principal, Security(get_principal)]) -> User:
    return principal.user


@router.get("/tokens", response_model=list[ApiTokenRead])
def list_tokens(
    principal: Annotated[Principal, Security(get_principal, scopes=["tokens:manage"])],
    service: AuthServiceDependency,
) -> list[AuthToken]:
    return service.list_api_tokens(principal.user.id)


@router.post("/tokens", response_model=ApiTokenCreated, status_code=status.HTTP_201_CREATED)
def create_api_token(
    payload: ApiTokenCreate,
    principal: Annotated[Principal, Security(get_principal, scopes=["tokens:manage"])],
    service: AuthServiceDependency,
) -> ApiTokenCreated:
    token, raw = service.create_api_token(payload, principal.user.id)
    return ApiTokenCreated(**ApiTokenRead.model_validate(token).model_dump(), token=raw)


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_api_token(
    token_id: str,
    principal: Annotated[Principal, Security(get_principal, scopes=["tokens:manage"])],
    service: AuthServiceDependency,
) -> None:
    service.revoke_api_token(token_id, principal.user.id)
