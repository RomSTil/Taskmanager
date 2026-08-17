from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Security
from sqlalchemy import select
from sqlalchemy.orm import Session

from ....database import get_session
from ....dependencies import Principal, get_principal
from .models import MarketOrder, YandexMarketAccount
from .schemas import (
    MarketAccountCreate,
    MarketAccountRead,
    MarketAccountUpdate,
    MarketOrderRead,
)
from .service import YandexMarketService

router = APIRouter(prefix="/integrations/yandex-market", tags=["yandex-market"])


def get_market_service(request: Request) -> YandexMarketService:
    return request.app.state.module_context.services.get(YandexMarketService)


@router.get("/accounts", response_model=list[MarketAccountRead])
def list_accounts(
    _: Annotated[Principal, Security(get_principal, scopes=["integrations:manage"])],
    session: Annotated[Session, Depends(get_session)],
) -> list[YandexMarketAccount]:
    return list(
        session.scalars(select(YandexMarketAccount).order_by(YandexMarketAccount.name))
    )


@router.post("/accounts", response_model=MarketAccountRead, status_code=201)
def create_account(
    payload: MarketAccountCreate,
    _: Annotated[Principal, Security(get_principal, scopes=["integrations:manage"])],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[YandexMarketService, Depends(get_market_service)],
) -> YandexMarketAccount:
    try:
        return service.create_account(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/accounts/{account_id}", response_model=MarketAccountRead)
def update_account(
    account_id: str,
    payload: MarketAccountUpdate,
    _: Annotated[Principal, Security(get_principal, scopes=["integrations:manage"])],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[YandexMarketService, Depends(get_market_service)],
) -> YandexMarketAccount:
    try:
        return service.update_account(session, account_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/accounts/{account_id}", status_code=204)
def delete_account(
    account_id: str,
    _: Annotated[Principal, Security(get_principal, scopes=["integrations:manage"])],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[YandexMarketService, Depends(get_market_service)],
) -> None:
    try:
        account = service.account(session, account_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.delete(account)
    session.commit()


@router.get("/orders", response_model=list[MarketOrderRead])
def list_orders(
    _: Annotated[Principal, Security(get_principal, scopes=["integrations:manage"])],
    session: Annotated[Session, Depends(get_session)],
) -> list[MarketOrder]:
    return list(session.scalars(select(MarketOrder).order_by(MarketOrder.discovered_at.desc())))


@router.post("/accounts/{account_id}/sync", status_code=202)
def sync_account(
    account_id: str,
    _: Annotated[Principal, Security(get_principal, scopes=["integrations:manage"])],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[YandexMarketService, Depends(get_market_service)],
) -> dict[str, int]:
    try:
        created = service.sync_account(session, service.account(session, account_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Yandex Market sync failed") from exc
    return {"new_orders": created}
