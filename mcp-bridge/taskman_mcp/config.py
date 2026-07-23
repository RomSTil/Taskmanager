import json
import os
from pathlib import Path
from urllib.parse import urlparse

import keyring


SERVICE_NAME = "taskman-mcp"
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def config_path() -> Path:
    base = Path(os.getenv("APPDATA") or Path.home() / ".config")
    return base / "Taskman" / "mcp.json"


def validate_api_url(api_url: str) -> str:
    normalized = api_url.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.username or parsed.password:
        raise ValueError("Taskman URL must not contain credentials")
    if parsed.scheme == "https" and parsed.hostname:
        return normalized
    if parsed.scheme == "http" and parsed.hostname in LOOPBACK_HOSTS:
        return normalized
    raise ValueError("Remote Taskman servers must use HTTPS")


def save_config(api_url: str, token: str) -> None:
    api_url = validate_api_url(api_url)
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"api_url": api_url.rstrip("/")}, indent=2), encoding="utf-8")
    keyring.set_password(SERVICE_NAME, api_url.rstrip("/"), token)


def load_config() -> tuple[str, str]:
    env_url = os.getenv("TASKMAN_API_URL")
    env_token = os.getenv("TASKMAN_MCP_TOKEN")
    if env_url and env_token:
        return env_url.rstrip("/"), env_token
    path = config_path()
    if not path.exists():
        raise RuntimeError("Taskman MCP is not configured. Run: taskman-mcp login")
    data = json.loads(path.read_text(encoding="utf-8"))
    api_url = validate_api_url(str(data["api_url"]))
    token = keyring.get_password(SERVICE_NAME, api_url)
    if not token:
        raise RuntimeError("Taskman MCP token is missing from the OS credential store")
    return api_url, token
