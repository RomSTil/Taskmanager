from datetime import datetime
from typing import Any

import httpx


class OzonApiError(RuntimeError):
    pass


class OzonSellerClient:
    def __init__(
        self,
        client_id: str,
        api_key: str,
        *,
        base_url: str = "https://api-seller.ozon.ru",
        http_client: httpx.Client | None = None,
    ) -> None:
        self.client_id = client_id
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.http_client = http_client

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Client-Id": self.client_id,
            "Api-Key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            if self.http_client is not None:
                response = self.http_client.post(path, headers=headers, json=payload)
            else:
                response = httpx.post(
                    f"{self.base_url}{path}",
                    headers=headers,
                    json=payload,
                    timeout=30,
                )
        except httpx.HTTPError as exc:
            raise OzonApiError(f"Ozon Seller API connection failed: {exc}") from exc
        if response.is_error:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text[:500]
            raise OzonApiError(f"Ozon Seller API error {response.status_code}: {detail}")
        try:
            return response.json()
        except ValueError as exc:
            raise OzonApiError("Ozon Seller API returned invalid JSON") from exc

    def _list_postings(
        self,
        path: str,
        since: datetime,
        to: datetime,
    ) -> list[dict[str, Any]]:
        offset = 0
        postings: list[dict[str, Any]] = []
        while True:
            payload = {
                "dir": "ASC",
                "filter": {
                    "since": since.isoformat().replace("+00:00", "Z"),
                    "to": to.isoformat().replace("+00:00", "Z"),
                    "status": "",
                },
                "limit": 1000,
                "offset": offset,
                "with": {
                    "analytics_data": False,
                    "financial_data": True,
                },
            }
            result = self._post(path, payload).get("result") or {}
            page = result.get("postings") or []
            postings.extend(item for item in page if isinstance(item, dict))
            if not result.get("has_next") or not page:
                return postings
            offset += len(page)

    def list_fbs_postings(self, since: datetime, to: datetime) -> list[dict[str, Any]]:
        return self._list_postings("/v3/posting/fbs/list", since, to)

    def list_fbo_postings(self, since: datetime, to: datetime) -> list[dict[str, Any]]:
        return self._list_postings("/v2/posting/fbo/list", since, to)
