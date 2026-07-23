import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from cryptography.fernet import Fernet, InvalidToken
from pwdlib import PasswordHash

from .config import get_settings


password_hasher = PasswordHash.recommended()
API_TOKEN_SCOPES = frozenset(
    {
        "projects:read",
        "projects:write",
        "tasks:read",
        "tasks:write",
        "notes:read",
        "notes:write",
    }
)
JWT_ISSUER = "taskman"
JWT_AUDIENCE = "taskman-api"


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return password_hasher.verify(password, password_hash)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(user_id: str) -> tuple[str, datetime]:
    settings = get_settings()
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.access_token_minutes)
    token = jwt.encode(
        {
            "sub": user_id,
            "exp": expires_at,
            "iat": datetime.now(UTC),
            "jti": secrets.token_urlsafe(16),
            "type": "access",
            "iss": JWT_ISSUER,
            "aud": JWT_AUDIENCE,
        },
        settings.effective_jwt_secret,
        algorithm="HS256",
    )
    return token, expires_at


def decode_access_token(token: str) -> str:
    payload = jwt.decode(
        token,
        get_settings().effective_jwt_secret,
        algorithms=["HS256"],
        issuer=JWT_ISSUER,
        audience=JWT_AUDIENCE,
        options={"require": ["sub", "exp", "iat", "jti", "type", "iss", "aud"]},
    )
    if payload.get("type") != "access" or not payload.get("sub"):
        raise jwt.InvalidTokenError("Invalid access token")
    return str(payload["sub"])


def new_refresh_token() -> str:
    return f"tmr_{secrets.token_urlsafe(48)}"


def new_api_token() -> str:
    return f"tm_{secrets.token_urlsafe(48)}"


def new_webhook_secret() -> str:
    return secrets.token_urlsafe(32).replace("-", "A").replace("_", "B")


def _fernet() -> Fernet:
    settings = get_settings()
    if settings.encryption_key:
        raw = settings.encryption_key.encode("ascii")
        try:
            return Fernet(raw)
        except ValueError:
            if settings.is_production:
                raise RuntimeError("TASKMAN_ENCRYPTION_KEY must be a valid Fernet key")
            raw = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
            return Fernet(raw)
    if settings.environment != "development":
        raise RuntimeError("TASKMAN_ENCRYPTION_KEY is required outside development")
    derived = hashlib.sha256((settings.effective_jwt_secret + ":encryption").encode()).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("Unable to decrypt stored integration secret") from exc


def constant_time_equal(left: str, right: str) -> bool:
    return secrets.compare_digest(left.encode(), right.encode())


def generate_encryption_key() -> str:
    return Fernet.generate_key().decode()
