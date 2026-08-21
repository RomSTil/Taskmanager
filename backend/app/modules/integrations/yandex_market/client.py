from typing import Any

import httpx

MARKET_API_BASE = "https://api.partner.market.yandex.ru"


class YandexMarketApiError(RuntimeError):
    pass


class YandexMarketClient:
    def __init__(
        self,
        api_key: str,
        campaign_id: int,
        *,
        timeout: float = 20,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.campaign_id = campaign_id
        self._headers = {"Api-Key": api_key, "Content-Type": "application/json"}
        self._timeout = timeout
        self._client = http_client

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: list[tuple[str, str]] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        client = self._client or httpx.Client(timeout=self._timeout)
        close_client = self._client is None
        try:
            response = client.request(
                method,
                f"{MARKET_API_BASE}{path}",
                headers=self._headers,
                params=params,
                json=payload,
            )
            try:
                body = response.json()
            except ValueError:
                body = {}
            if response.is_error or body.get("status") == "ERROR":
                errors = body.get("errors") or []
                details = "; ".join(
                    " ".join(
                        part
                        for part in (
                            str(error.get("code") or "").strip(),
                            str(error.get("message") or "").strip(),
                        )
                        if part
                    )
                    for error in errors[:3]
                )
                raise YandexMarketApiError(
                    f"Yandex Market API error {details or response.status_code}"
                )
            return dict(body)
        finally:
            if close_client:
                client.close()

    def get_processing_orders(self) -> list[dict[str, Any]]:
        orders: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params = [
                ("status", "PROCESSING"),
                ("substatus", "STARTED"),
                ("limit", "50"),
            ]
            if page_token:
                params.append(("pageToken", page_token))
            body = self._request(
                "GET",
                f"/v2/campaigns/{self.campaign_id}/orders",
                params=params,
            )
            # The current seller API returns orders at the response root. Keep
            # compatibility with the wrapped form used by some API examples.
            result = body.get("result") or body
            orders.extend(dict(order) for order in result.get("orders") or [])
            page_token = (result.get("paging") or {}).get("nextPageToken")
            if not page_token:
                return orders

    def get_order(self, order_id: int) -> dict[str, Any]:
        body = self._request(
            "GET",
            f"/v2/campaigns/{self.campaign_id}/orders/{order_id}",
        )
        result = body.get("result") or body
        return dict(result.get("order") or result)

    def mark_ready_to_ship(self, order_id: int) -> dict[str, Any]:
        return self._request(
            "PUT",
            f"/v2/campaigns/{self.campaign_id}/orders/{order_id}/status",
            payload={
                "order": {
                    "status": "PROCESSING",
                    "substatus": "READY_TO_SHIP",
                }
            },
        )
