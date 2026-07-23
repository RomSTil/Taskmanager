from typing import Any


class ApplicationError(Exception):
    """Expected application failure that is safe to expose through the API."""

    def __init__(
        self,
        status_code: int,
        detail: str | dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail
        self.headers = headers


class AuthenticationError(ApplicationError):
    def __init__(self, detail: str = "Invalid credentials") -> None:
        super().__init__(401, detail, headers={"WWW-Authenticate": "Bearer"})


class AuthorizationError(ApplicationError):
    def __init__(self, detail: str = "Forbidden") -> None:
        super().__init__(403, detail)


class ConflictError(ApplicationError):
    def __init__(self, detail: str | dict[str, Any]) -> None:
        super().__init__(409, detail)


class NotFoundError(ApplicationError):
    def __init__(self, detail: str) -> None:
        super().__init__(404, detail)


class RateLimitError(ApplicationError):
    def __init__(self, retry_after: int) -> None:
        super().__init__(
            429,
            "Too many authentication attempts",
            headers={"Retry-After": str(retry_after)},
        )


class ValidationError(ApplicationError):
    def __init__(self, detail: str | dict[str, Any]) -> None:
        super().__init__(422, detail)
