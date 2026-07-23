import json
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.errors import RateLimitError
from app.core.modules import ModuleRegistry, RouterModule
from app.main import create_app
from app.services.auth import LoginRateLimiter


def test_refresh_token_cannot_be_replayed(client: TestClient) -> None:
    created = client.post(
        "/api/v1/auth/setup",
        json={"username": "owner", "password": "a-strong-password"},
    )
    refresh_token = created.json()["refresh_token"]

    first = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})

    assert first.status_code == 200
    assert replay.status_code == 401


def test_scoped_token_cannot_manage_tokens_or_integrations(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    created = client.post(
        "/api/v1/auth/tokens",
        headers=auth_headers,
        json={"name": "reader", "scopes": ["projects:read"]},
    )
    scoped_headers = {"Authorization": f"Bearer {created.json()['token']}"}

    assert client.get("/api/v1/auth/tokens", headers=scoped_headers).status_code == 403
    assert (
        client.get("/api/v1/integrations/telegram/bots", headers=scoped_headers).status_code
        == 403
    )


def test_login_rate_limiter_expires_and_clears() -> None:
    limiter = LoginRateLimiter(attempts=3, window_seconds=300)
    for _ in range(3):
        limiter.check("client:owner")
        limiter.failed("client:owner")

    with pytest.raises(RateLimitError) as caught:
        limiter.check("client:owner")
    assert getattr(caught.value, "status_code", None) == 429

    limiter.succeeded("client:owner")
    limiter.check("client:owner")


def test_production_settings_reject_development_secrets() -> None:
    settings = Settings(
        environment="production",
        public_url="https://tasks.example.com",
        trusted_hosts="tasks.example.com",
        jwt_secret=None,
        setup_token="s" * 32,
        encryption_key=Fernet.generate_key().decode(),
    )

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        settings.validate_runtime()


def test_module_registry_rejects_cycles_and_installs_custom_router() -> None:
    with pytest.raises(ValueError, match="Cyclic"):
        ModuleRegistry(
            [
                RouterModule("first", dependencies=("second",)),
                RouterModule("second", dependencies=("first",)),
            ]
        )

    router = APIRouter()

    @router.get("/example")
    def example() -> dict[str, bool]:
        return {"ok": True}

    app = create_app(initialize_database=False, modules=[RouterModule("example", router)])
    with TestClient(app) as custom_client:
        assert custom_client.get("/api/v1/example").json() == {"ok": True}


def test_current_tauri_client_has_a_csp() -> None:
    config_path = (
        Path(__file__).parents[2]
        / "frontend"
        / "task manager"
        / "src-tauri"
        / "tauri.conf.json"
    )
    config = json.loads(config_path.read_text(encoding="utf-8"))

    csp = config["app"]["security"]["csp"]
    assert csp
    assert "script-src 'self'" in csp
    assert "object-src 'none'" in csp
