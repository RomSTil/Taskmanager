import csv
import io
from collections.abc import Iterable
from datetime import date
from typing import Any

import httpx


DIRECT_API_BASE = "https://api.direct.yandex.com/json/v5"


class DirectReportPending(RuntimeError):
    def __init__(self, retry_after: int = 60) -> None:
        super().__init__("Yandex Direct report is still being generated")
        self.retry_after = max(5, retry_after)


class DirectApiError(RuntimeError):
    def __init__(self, code: int | str, message: str) -> None:
        super().__init__(message)
        self.code = code


class YandexDirectClient:
    def __init__(
        self,
        token: str,
        *,
        client_login: str | None = None,
        timeout: float = 30,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept-Language": "ru",
        }
        if client_login:
            self._headers["Client-Login"] = client_login
        self._timeout = timeout
        self._client = http_client

    def _post_json(self, service: str, payload: dict[str, Any]) -> dict[str, Any]:
        client = self._client or httpx.Client(timeout=self._timeout)
        close_client = self._client is None
        try:
            response = client.post(
                f"{DIRECT_API_BASE}/{service}",
                headers=self._headers,
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
            if "error" in body:
                error = body["error"]
                code = error.get("error_code", "unknown")
                message = error.get("error_string") or error.get("error_detail")
                detail = error.get("error_detail")
                parts = [f"Yandex Direct API error {code}"]
                if message:
                    parts.append(str(message))
                if detail and detail != message:
                    parts.append(str(detail))
                raise DirectApiError(code, ": ".join(parts))
            return dict(body.get("result", {}))
        finally:
            if close_client:
                client.close()

    def get_campaigns(self) -> list[dict[str, Any]]:
        result = self._post_json(
            "campaigns",
            {
                "method": "get",
                "params": {
                    "SelectionCriteria": {},
                    "FieldNames": [
                        "Id",
                        "Name",
                        "State",
                        "Status",
                        "StatusPayment",
                        "Currency",
                        "Funds",
                        "Statistics",
                    ],
                    "Page": {"Limit": 10000},
                },
            },
        )
        return list(result.get("Campaigns", []))

    def get_report(
        self,
        date_from: date,
        date_to: date,
        *,
        campaign_ids: Iterable[int] | None = None,
    ) -> list[dict[str, str]]:
        filters: list[dict[str, Any]] = []
        ids = list(campaign_ids or [])
        if ids:
            filters.append(
                {
                    "Field": "CampaignId",
                    "Operator": "IN",
                    "Values": [str(item) for item in ids],
                }
            )
        payload = {
            "params": {
                "SelectionCriteria": {
                    "DateFrom": date_from.isoformat(),
                    "DateTo": date_to.isoformat(),
                    "Filter": filters,
                },
                "FieldNames": [
                    "Date",
                    "CampaignId",
                    "CampaignName",
                    "Impressions",
                    "Clicks",
                    "Cost",
                    "Conversions",
                ],
                "ReportName": f"taskman-{date_from.isoformat()}-{date_to.isoformat()}",
                "ReportType": "CAMPAIGN_PERFORMANCE_REPORT",
                "DateRangeType": "CUSTOM_DATE",
                "Format": "TSV",
                "IncludeVAT": "NO",
                "IncludeDiscount": "NO",
            }
        }
        headers = {
            **self._headers,
            "processingMode": "auto",
            "returnMoneyInMicros": "false",
            "skipReportHeader": "true",
            "skipReportSummary": "true",
        }
        client = self._client or httpx.Client(timeout=self._timeout)
        close_client = self._client is None
        try:
            response = client.post(f"{DIRECT_API_BASE}/reports", headers=headers, json=payload)
            if response.status_code in {201, 202}:
                retry_header = response.headers.get("retryIn", "60")
                raise DirectReportPending(int(retry_header) if retry_header.isdigit() else 60)
            response.raise_for_status()
            reader = csv.DictReader(io.StringIO(response.text), delimiter="\t")
            return [dict(row) for row in reader]
        finally:
            if close_client:
                client.close()
