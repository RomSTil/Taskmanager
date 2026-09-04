import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class TaskmanClient:
    def __init__(self, api_url: str, *, runner_token: str | None = None, owner_token: str | None = None) -> None:
        self.api_url = api_url.rstrip("/")
        self.runner_token = runner_token
        self.owner_token = owner_token

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        assignment_token: str | None = None,
    ) -> dict[str, Any] | list[Any] | None:
        headers = {"Accept": "application/json"}
        body: bytes | None = None
        if self.runner_token:
            headers["X-Taskman-Runner-Token"] = self.runner_token
        if self.owner_token:
            headers["Authorization"] = f"Bearer {self.owner_token}"
        if assignment_token:
            headers["X-Taskman-Assignment"] = assignment_token
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(f"{self.api_url}/api/v1{path}", data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310 - configured owner endpoint
                raw = response.read()
        except HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace")[:1_000]
            raise RuntimeError(f"Taskman API returned HTTP {exc.code}: {message}") from exc
        except URLError as exc:
            raise RuntimeError(f"Taskman API is unavailable: {exc.reason}") from exc
        return json.loads(raw) if raw else None
