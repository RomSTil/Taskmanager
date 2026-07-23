from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import DirectCampaignSnapshot, DirectDailyStat, YandexDirectAccount


MICRO = Decimal("1000000")


def _money_from_micros(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return (Decimal(str(value)) / MICRO).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _number(value: Any, *, places: str = "0.01") -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(Decimal(places))
    except (InvalidOperation, ValueError):
        return Decimal("0")


class YandexDirectRepository:
    def save_campaigns(
        self,
        session: Session,
        account: YandexDirectAccount,
        campaigns: list[dict[str, Any]],
    ) -> list[DirectCampaignSnapshot]:
        checked_at = datetime.now(UTC)
        stored: list[DirectCampaignSnapshot] = []
        for item in campaigns:
            campaign_id = int(item["Id"])
            snapshot = session.scalar(
                select(DirectCampaignSnapshot).where(
                    DirectCampaignSnapshot.account_id == account.id,
                    DirectCampaignSnapshot.campaign_id == campaign_id,
                )
            )
            funds = item.get("Funds") or {}
            mode = str(funds.get("Mode") or "")
            campaign_funds = funds.get("CampaignFunds") or {}
            balance = (
                _money_from_micros(campaign_funds.get("Balance"))
                if mode == "CAMPAIGN_FUNDS"
                else None
            )
            values = {
                "name": str(item.get("Name") or campaign_id)[:255],
                "state": str(item.get("State") or "UNKNOWN")[:40],
                "status": str(item.get("Status") or "UNKNOWN")[:40],
                "currency": str(item.get("Currency") or "")[:16],
                "balance": balance,
                "uses_shared_account": mode == "SHARED_ACCOUNT_FUNDS",
                "data": item,
                "checked_at": checked_at,
            }
            if snapshot is None:
                snapshot = DirectCampaignSnapshot(
                    account_id=account.id,
                    campaign_id=campaign_id,
                    **values,
                )
                session.add(snapshot)
            else:
                for field, value in values.items():
                    setattr(snapshot, field, value)
            stored.append(snapshot)
        session.flush()
        return stored

    def save_stats(
        self,
        session: Session,
        account: YandexDirectAccount,
        rows: list[dict[str, str]],
    ) -> list[DirectDailyStat]:
        updated_at = datetime.now(UTC)
        stored: list[DirectDailyStat] = []
        for row in rows:
            campaign_id = int(row.get("CampaignId") or 0)
            stat_date = date.fromisoformat(str(row["Date"]))
            stat = session.scalar(
                select(DirectDailyStat).where(
                    DirectDailyStat.account_id == account.id,
                    DirectDailyStat.campaign_id == campaign_id,
                    DirectDailyStat.stat_date == stat_date,
                )
            )
            values = {
                "campaign_name": str(row.get("CampaignName") or campaign_id)[:255],
                "impressions": int(float(row.get("Impressions") or 0)),
                "clicks": int(float(row.get("Clicks") or 0)),
                "cost": _number(row.get("Cost")),
                "conversions": _number(row.get("Conversions"), places="0.0001"),
                "updated_at": updated_at,
            }
            if stat is None:
                stat = DirectDailyStat(
                    account_id=account.id,
                    campaign_id=campaign_id,
                    stat_date=stat_date,
                    **values,
                )
                session.add(stat)
            else:
                for field, value in values.items():
                    setattr(stat, field, value)
            stored.append(stat)
        session.flush()
        return stored
