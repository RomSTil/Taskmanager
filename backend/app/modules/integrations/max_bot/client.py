from typing import Any

import httpx

MAX_API_BASE = "https://platform-api2.max.ru"


class MaxApiClient:
    def __init__(
        self,
        token: str,
        *,
        verify_tls: bool = True,
        timeout: float = 20,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._headers = {"Authorization": token, "Content-Type": "application/json"}
        self._timeout = timeout
        self._client = http_client
        self._verify_tls = verify_tls

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        client = self._client or httpx.Client(timeout=self._timeout, verify=self._verify_tls)
        close_client = self._client is None
        try:
            response = client.request(
                method,
                f"{MAX_API_BASE}{path}",
                headers=self._headers,
                params=params,
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
            if body.get("success") is False:
                raise RuntimeError("MAX API rejected the request")
            return dict(body)
        finally:
            if close_client:
                client.close()

    def send_message(
        self,
        target_type: str,
        target_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        parameter = "chat_id" if target_type == "chat" else "user_id"
        return self._request(
            "POST",
            "/messages",
            params={parameter: target_id},
            payload=payload,
        )

    def answer_callback(
        self,
        callback_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/answers",
            params={"callback_id": callback_id},
            payload={"message": payload},
        )

    def register_webhook(
        self,
        url: str,
        secret: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/subscriptions",
            payload={
                "url": url,
                "update_types": [
                    "bot_started",
                    "bot_added",
                    "message_created",
                    "message_callback",
                ],
                "secret": secret,
            },
        )
