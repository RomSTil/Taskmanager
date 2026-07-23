from collections import deque
from datetime import UTC, datetime, timedelta
from threading import Lock

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import Settings
from ..core.errors import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)
from ..models import AuthToken, Project, TokenKind, User
from ..schemas import ApiTokenCreate, LoginRequest, SetupRequest, TokenPair, UserRead
from ..security import (
    API_TOKEN_SCOPES,
    constant_time_equal,
    create_access_token,
    hash_password,
    hash_token,
    new_api_token,
    new_refresh_token,
    verify_password,
)


class LoginRateLimiter:
    """Process-local guard for the single-process API deployment."""

    def __init__(
        self, attempts: int, window_seconds: int, *, max_tracked_keys: int = 10_000
    ) -> None:
        self._attempts = attempts
        self._window_seconds = window_seconds
        self._max_tracked_keys = max_tracked_keys
        self._failures: dict[str, deque[datetime]] = {}
        self._lock = Lock()

    def check(self, key: str) -> None:
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=self._window_seconds)
        with self._lock:
            failures = self._failures.get(key)
            if failures is None:
                if len(self._failures) >= self._max_tracked_keys:
                    self._failures.pop(next(iter(self._failures)))
                failures = self._failures[key] = deque()
            while failures and failures[0] <= cutoff:
                failures.popleft()
            if len(failures) >= self._attempts:
                retry_after = max(1, int((failures[0] + timedelta(seconds=self._window_seconds) - now).total_seconds()))
                raise RateLimitError(retry_after)

    def failed(self, key: str) -> None:
        with self._lock:
            failures = self._failures.get(key)
            if failures is None:
                if len(self._failures) >= self._max_tracked_keys:
                    self._failures.pop(next(iter(self._failures)))
                failures = self._failures[key] = deque()
            failures.append(datetime.now(UTC))

    def succeeded(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


class AuthService:
    """Authentication use-cases and transaction boundaries."""

    _dummy_password_hash = hash_password("taskman-dummy-password-not-used")

    def __init__(
        self,
        session: Session,
        settings: Settings,
        rate_limiter: LoginRateLimiter,
    ) -> None:
        self.session = session
        self.settings = settings
        self.rate_limiter = rate_limiter

    @staticmethod
    def _expired(value: datetime | None) -> bool:
        if value is None:
            return False
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value < datetime.now(UTC)

    def setup_required(self) -> bool:
        return (self.session.scalar(select(func.count(User.id))) or 0) == 0

    def setup(self, payload: SetupRequest, supplied_token: str | None) -> TokenPair:
        if not self.setup_required():
            raise ConflictError("Owner account already exists")
        if self.settings.setup_token and (
            not supplied_token or not constant_time_equal(supplied_token, self.settings.setup_token)
        ):
            raise AuthorizationError("Invalid setup token")

        user = User(username=payload.username.strip(), password_hash=hash_password(payload.password))
        self.session.add(user)
        self.session.add(
            Project(
                name="Личное пространство",
                key="HOME",
                description="Общие задачи и заметки до распределения по проектам.",
                color="#8b5cf6",
            )
        )
        try:
            self.session.flush()
            pair = self._issue_pair(user)
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError("Owner account already exists") from exc
        self.session.refresh(user)
        return pair

    def login(self, payload: LoginRequest, attempt_key: str) -> TokenPair:
        self.rate_limiter.check(attempt_key)
        user = self.session.scalar(select(User).where(User.username == payload.username.strip()))
        password_hash = user.password_hash if user else self._dummy_password_hash
        password_valid = verify_password(payload.password, password_hash)
        if not user or not user.is_active or not password_valid:
            self.rate_limiter.failed(attempt_key)
            raise AuthenticationError("Invalid username or password")
        self.rate_limiter.succeeded(attempt_key)
        pair = self._issue_pair(user)
        self.session.commit()
        return pair

    def refresh(self, raw_token: str) -> TokenPair:
        now = datetime.now(UTC)
        consumed = self.session.execute(
            update(AuthToken)
            .where(
                AuthToken.kind == TokenKind.refresh,
                AuthToken.token_hash == hash_token(raw_token),
                AuthToken.revoked_at.is_(None),
                AuthToken.expires_at > now,
            )
            .values(revoked_at=now)
            .returning(AuthToken.user_id)
        ).scalar_one_or_none()
        if not consumed:
            self.session.rollback()
            raise AuthenticationError("Invalid refresh token")
        user = self.session.get(User, consumed)
        if not user or not user.is_active:
            self.session.rollback()
            raise AuthenticationError("Inactive owner account")
        pair = self._issue_pair(user)
        self.session.commit()
        return pair

    def logout(self, raw_token: str) -> None:
        self.session.execute(
            update(AuthToken)
            .where(
                AuthToken.kind == TokenKind.refresh,
                AuthToken.token_hash == hash_token(raw_token),
                AuthToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        self.session.commit()

    def list_api_tokens(self, user_id: str) -> list[AuthToken]:
        return list(
            self.session.scalars(
                select(AuthToken)
                .where(AuthToken.kind == TokenKind.api, AuthToken.user_id == user_id)
                .order_by(AuthToken.created_at.desc())
            )
        )

    def create_api_token(self, payload: ApiTokenCreate, user_id: str) -> tuple[AuthToken, str]:
        unknown = set(payload.scopes) - API_TOKEN_SCOPES
        if unknown:
            raise ValidationError(f"Unknown API token scopes: {', '.join(sorted(unknown))}")
        if payload.expires_at and self._expired(payload.expires_at):
            raise ValidationError("API token expiration must be in the future")
        raw = new_api_token()
        token = AuthToken(
            user_id=user_id,
            name=payload.name,
            kind=TokenKind.api,
            token_hash=hash_token(raw),
            scopes=sorted(set(payload.scopes)),
            expires_at=payload.expires_at,
        )
        self.session.add(token)
        self.session.commit()
        self.session.refresh(token)
        return token, raw

    def revoke_api_token(self, token_id: str, user_id: str) -> None:
        token = self.session.scalar(
            select(AuthToken).where(
                AuthToken.id == token_id,
                AuthToken.kind == TokenKind.api,
                AuthToken.user_id == user_id,
            )
        )
        if not token:
            raise NotFoundError("API token not found")
        token.revoked_at = datetime.now(UTC)
        self.session.commit()

    def _issue_pair(self, user: User) -> TokenPair:
        access, expires_at = create_access_token(user.id)
        refresh = new_refresh_token()
        self.session.add(
            AuthToken(
                user_id=user.id,
                name="desktop session",
                kind=TokenKind.refresh,
                token_hash=hash_token(refresh),
                scopes=["*"],
                expires_at=datetime.now(UTC) + timedelta(days=self.settings.refresh_token_days),
            )
        )
        self.session.flush()
        return TokenPair(
            access_token=access,
            refresh_token=refresh,
            expires_at=expires_at,
            user=UserRead.model_validate(user),
        )
