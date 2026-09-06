import argparse
import getpass
from pathlib import Path

from .client import TaskmanClient
from .config import RunnerConfig, load_config, save_config
from .credentials import load_runner_token, save_runner_token
from .runner import LocalRunner


def _register(args: argparse.Namespace) -> None:
    owner_token = getpass.getpass("Одноразовый API token для Codex Runner: ").strip()
    if not owner_token:
        raise RuntimeError("Owner API token is required for pairing")
    response = TaskmanClient(args.api_url, owner_token=owner_token).request(
        "POST",
        "/agent-runners/register",
        payload={
            "name": args.name,
            "version": "0.1.0",
            "capabilities": ["browser", "git", "codex"],
            "max_concurrency": 1,
        },
    )
    if not isinstance(response, dict):
        raise RuntimeError("Unexpected response while registering runner")
    runner_id = str(response["id"])
    save_runner_token(runner_id, str(response["runner_token"]))
    save_config(
        RunnerConfig(
            api_url=args.api_url.rstrip("/"),
            runner_id=runner_id,
            workspace_path=str(Path(args.workspace).resolve()),
            poll_seconds=args.poll_seconds,
            codex_command=args.codex_command,
            codex_model=args.codex_model,
        )
    )
    print(f"Runner paired: {runner_id}. Token is stored in Windows Credential Manager.")


def _run(_: argparse.Namespace) -> None:
    config = load_config()
    LocalRunner(config, load_runner_token(config.runner_id)).run_forever()


def main() -> None:
    parser = argparse.ArgumentParser(prog="taskman-agent-runner")
    subparsers = parser.add_subparsers(required=True)
    register = subparsers.add_parser("register", help="Pair this Windows PC with Taskman")
    register.add_argument("--api-url", required=True)
    register.add_argument("--name", required=True)
    register.add_argument("--workspace", required=True, help="Local Git repository for code tasks")
    register.add_argument("--poll-seconds", type=float, default=20.0)
    register.add_argument("--codex-command", default="codex")
    register.add_argument("--codex-model", default="auto")
    register.set_defaults(func=_register)
    run = subparsers.add_parser("run", help="Start the polling runner")
    run.set_defaults(func=_run)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
