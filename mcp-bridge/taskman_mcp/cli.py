import argparse
import getpass

import httpx

from .config import save_config


def configure(api_url: str | None, token: str | None) -> None:
    url = (api_url or input("Taskman URL: ")).strip().rstrip("/")
    raw_token = token or getpass.getpass("Taskman MCP token: ")
    response = httpx.get(
        f"{url}/api/v1/projects",
        headers={"Authorization": f"Bearer {raw_token}"},
        timeout=15,
    )
    response.raise_for_status()
    save_config(url, raw_token)
    print("Taskman MCP credentials saved in the OS credential store.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="taskman-mcp")
    subparsers = parser.add_subparsers(dest="command")
    login = subparsers.add_parser("login", help="Configure server URL and scoped token")
    login.add_argument("--url")
    login.add_argument("--token")
    subparsers.add_parser("serve", help="Run the stdio MCP server")
    args = parser.parse_args()
    if args.command == "login":
        configure(args.url, args.token)
        return
    from .server import serve

    serve()


if __name__ == "__main__":
    main()
