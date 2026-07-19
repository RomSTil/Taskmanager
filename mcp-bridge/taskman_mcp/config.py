import json
import os
from pathlib import Path

import keyring


SERVICE_NAME = "taskman-mcp"


def config_path() -> Path:
    base = Path(os.getenv("APPDATA") or Path.home() / ".config")
    return base / "Taskman" / "mcp.json"


def save_config(api_url: str, token: str) -> None:
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
    api_url = str(data["api_url"]).rstrip("/")
    token = keyring.get_password(SERVICE_NAME, api_url)
    if not token:
        raise RuntimeError("Taskman MCP token is missing from the OS credential store")
    return api_url, token
