import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunnerConfig:
    api_url: str
    runner_id: str
    workspace_path: str
    poll_seconds: float = 20.0
    codex_command: str = "codex"
    codex_model: str = "gpt-6-astra"


def config_path() -> Path:
    root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return root / "Taskman Agent Runner" / "runner.json"


def save_config(config: RunnerConfig) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")


def load_config() -> RunnerConfig:
    path = config_path()
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
        return RunnerConfig(**content)
    except FileNotFoundError as exc:
        raise RuntimeError("Runner is not paired. Run: taskman-agent-runner register") from exc
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Runner configuration is invalid: {path}") from exc
