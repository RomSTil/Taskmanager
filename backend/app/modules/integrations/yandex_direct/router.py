from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Security
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ....database import get_session
from ....dependencies import Principal, get_principal
from .models import (
    DirectCampaignSnapshot,
    DirectDailyStat,
    IntegrationJob,
    YandexDirectAccount,
)
from .schemas import (
    DirectAccountCreate,
    DirectAccountRead,
    DirectAccountUpdate,
    DirectCampaignRead,
    DirectDailyStatRead,
    DirectJobCreate,
    DirectJobRead,
)
from .service import YandexDirectService


router = APIRouter(prefix="/integrations/yandex-direct", tags=["yandex-direct"])


def get_direct_service(request: Request) -> YandexDirectService:
    return request.app.state.module_context.services.get(YandexDirectService)


@router.get("/accounts", response_model=list[DirectAccountRead])
def list_accounts(
    _: Annotated[Principal, Security(get_principal, scopes=["integrations:manage"])],
    session: Annotated[Session, Depends(get_session)],
) -> list[YandexDirectAccount]:
    return list(session.scalars(select(YandexDirectAccount).order_by(YandexDirectAccount.name)))


@router.post("/accounts", response_model=DirectAccountRead, status_code=201)
def create_account(
    payload: DirectAccountCreate,
    _: Annotated[Principal, Security(get_principal, scopes=["integrations:manage"])],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[YandexDirectService, Depends(get_direct_service)],
) -> YandexDirectAccount:
    try:
        return service.create_account(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/accounts/{account_id}", response_model=DirectAccountRead)
def update_account(
    account_id: str,
    payload: DirectAccountUpdate,
    _: Annotated[Principal, Security(get_principal, scopes=["integrations:manage"])],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[YandexDirectService, Depends(get_direct_service)],
) -> YandexDirectAccount:
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
    service: Annotated[YandexDirectService, Depends(get_direct_service)],
) -> None:
    try:
        account = service.account(session, account_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.delete(account)
    session.commit()


@router.post("/accounts/{account_id}/jobs", response_model=DirectJobRead, status_code=202)
def create_job(
    account_id: str,
    payload: DirectJobCreate,
    _: Annotated[Principal, Security(get_principal, scopes=["integrations:manage"])],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[YandexDirectService, Depends(get_direct_service)],
) -> IntegrationJob:
    try:
        return service.queue_requested_job(session, account_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Duplicate job") from exc


@router.get("/jobs/{job_id}", response_model=DirectJobRead)
def get_job(
    job_id: str,
    _: Annotated[Principal, Security(get_principal, scopes=["integrations:manage"])],
    session: Annotated[Session, Depends(get_session)],
) -> IntegrationJob:
    job = session.get(IntegrationJob, job_id)
    if job is None or job.provider != "yandex_direct":
        raise HTTPException(status_code=404, detail="Direct job not found")
    return job


@router.get("/accounts/{account_id}/campaigns", response_model=list[DirectCampaignRead])
def list_campaigns(
    account_id: str,
    _: Annotated[Principal, Security(get_principal, scopes=["integrations:manage"])],
    session: Annotated[Session, Depends(get_session)],
) -> list[DirectCampaignSnapshot]:
    return list(
        session.scalars(
            select(DirectCampaignSnapshot)
            .where(DirectCampaignSnapshot.account_id == account_id)
            .order_by(DirectCampaignSnapshot.name)
        )
    )


@router.get("/accounts/{account_id}/stats", response_model=list[DirectDailyStatRead])
def list_stats(
    account_id: str,
    _: Annotated[Principal, Security(get_principal, scopes=["integrations:manage"])],
    session: Annotated[Session, Depends(get_session)],
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[DirectDailyStat]:
    query = select(DirectDailyStat).where(DirectDailyStat.account_id == account_id)
    if date_from:
        query = query.where(DirectDailyStat.stat_date >= date_from)
    if date_to:
        query = query.where(DirectDailyStat.stat_date <= date_to)
    return list(
        session.scalars(
            query.order_by(DirectDailyStat.stat_date.desc(), DirectDailyStat.campaign_name)
        )
    )
