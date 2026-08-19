from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Security
from sqlalchemy import select
from sqlalchemy.orm import Session

from ....database import get_session
from ....dependencies import Principal, get_principal
from .client import OzonApiError
from .models import OzonPosting, OzonSellerAccount
from .schemas import OzonAccountCreate, OzonAccountRead, OzonPostingRead, OzonSyncRead
from .service import OzonSellerService


router = APIRouter(prefix="/integrations/ozon", tags=["ozon-seller"])


def get_ozon_service(request: Request) -> OzonSellerService:
    return request.app.state.module_context.services.get(OzonSellerService)


@router.get("/accounts", response_model=list[OzonAccountRead])
def list_accounts(
    _: Annotated[Principal, Security(get_principal, scopes=["integrations:manage"])],
    session: Annotated[Session, Depends(get_session)],
) -> list[OzonSellerAccount]:
    return list(session.scalars(select(OzonSellerAccount).order_by(OzonSellerAccount.name)))


@router.post("/accounts", response_model=OzonAccountRead, status_code=201)
def create_account(
    payload: OzonAccountCreate,
    _: Annotated[Principal, Security(get_principal, scopes=["integrations:manage"])],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[OzonSellerService, Depends(get_ozon_service)],
) -> OzonSellerAccount:
    try:
        return service.create_account(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/accounts/{account_id}", status_code=204)
def delete_account(
    account_id: str,
    _: Annotated[Principal, Security(get_principal, scopes=["integrations:manage"])],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[OzonSellerService, Depends(get_ozon_service)],
) -> None:
    try:
        account = service.account(session, account_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.delete(account)
    session.commit()


@router.post("/accounts/{account_id}/sync", response_model=OzonSyncRead)
def sync_account(
    account_id: str,
    _: Annotated[Principal, Security(get_principal, scopes=["integrations:manage"])],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[OzonSellerService, Depends(get_ozon_service)],
) -> dict[str, object]:
    try:
        account = service.account(session, account_id)
        return service.sync_account(session, account)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OzonApiError as exc:
        session.rollback()
        account = session.get(OzonSellerAccount, account_id)
        if account:
            account.last_error = str(exc)[:1000]
            session.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/accounts/{account_id}/postings", response_model=list[OzonPostingRead])
def list_postings(
    account_id: str,
    _: Annotated[Principal, Security(get_principal, scopes=["integrations:manage"])],
    session: Annotated[Session, Depends(get_session)],
    limit: int = 50,
) -> list[OzonPosting]:
    return list(
        session.scalars(
            select(OzonPosting)
            .where(OzonPosting.account_id == account_id)
            .order_by(OzonPosting.first_seen_at.desc())
            .limit(min(max(limit, 1), 200))
        )
    )
