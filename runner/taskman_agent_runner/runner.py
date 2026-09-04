import json
import subprocess
import time
from pathlib import Path
from typing import Any

from .client import TaskmanClient
from .config import RunnerConfig


ROLE_PROMPTS = {
    "coordinator": "Ты координатор. Выбери следующий проверяемый шаг и делегируй его через агентские события.",
    "researcher_developer": "Ты исследователь или разработчик. Выполни работу и фиксируй проверяемые результаты в TaskManager MCP.",
    "tester": "Ты тестировщик. Проверь критерии результата и верни воспроизводимые дефекты либо готовность к оценке владельца.",
    "visual_reviewer": "Ты визуальный ревьюер. Проверь иерархию, текст, контраст, адаптивность и отсутствие шаблонного нейрослопа.",
    "deploy": "Ты деплой-агент. Публикация возможна только при одобренном action publication.",
}


class LocalRunner:
    def __init__(self, config: RunnerConfig, runner_token: str) -> None:
        self.config = config
        self.client = TaskmanClient(config.api_url, runner_token=runner_token)

    def run_forever(self) -> None:
        while True:
            try:
                self.client.request(
                    "POST",
                    f"/agent-runners/{self.config.runner_id}/heartbeat",
                    payload={"version": "0.1.0", "capabilities": ["browser", "git", "codex"]},
                )
                assignment = self.client.request(
                    "POST", f"/agent-runners/{self.config.runner_id}/claim"
                )
                if assignment:
                    self._execute(assignment)
            except KeyboardInterrupt:
                return
            except Exception as exc:  # noqa: BLE001
                # Only the exception class is sent to prevent local paths or secrets leaking to the server.
                try:
                    self.client.request(
                        "POST",
                        f"/agent-runners/{self.config.runner_id}/heartbeat",
                        payload={"last_error": f"Runner error: {type(exc).__name__}"},
                    )
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(self.config.poll_seconds)

    def _execute(self, assignment: dict[str, Any]) -> None:
        run = assignment["run"]
        assignment_token = assignment["assignment_token"]
        run_id = str(run["id"])
        role = str(run["role"])
        headers = assignment_token
        self.client.request(
            "POST",
            f"/agent-runs/{run_id}/events",
            assignment_token=headers,
            payload={"event_type": "role_started", "summary": "Codex начал назначенную роль."},
        )
        worktree: Path | None = None
        try:
            if role == "researcher_developer" and "code_preview" in run.get("allowed_actions", []):
                worktree = self._create_worktree(run_id)
            elif "code_preview" in run.get("allowed_actions", []):
                existing = self._worktree_path(run_id)
                if existing.exists():
                    worktree = existing
            result, cancelled = self._run_codex(run, worktree)
            if cancelled:
                return
            if result.returncode != 0:
                self.client.request(
                    "POST",
                    f"/agent-runs/{run_id}/complete",
                    assignment_token=headers,
                    payload={
                        "outcome": "failed",
                        "summary": "Codex не смог завершить этап.",
                        "error_code": "codex_exit_nonzero",
                        "error_message": "Локальный Codex завершился с ошибкой. Проверьте runner и повторите запуск.",
                    },
                )
                return
            if next_role := self._next_role(run):
                self.client.request(
                    "POST",
                    f"/agent-runs/{run_id}/events",
                    assignment_token=headers,
                    payload={
                        "event_type": "role_completed",
                        "summary": "Роль завершила свой этап; передаю результат следующему специалисту.",
                        "payload": {"next_role": next_role, "next_context": {"previous_role": role}},
                    },
                )
                return
            self.client.request(
                "POST",
                f"/agent-runs/{run_id}/complete",
                assignment_token=headers,
                payload={
                    "outcome": "owner_review",
                    "summary": "Codex завершил назначенный этап. Результаты и ссылки сохранены в TaskManager.",
                },
            )
        except Exception as exc:  # noqa: BLE001
            self.client.request(
                "POST",
                f"/agent-runs/{run_id}/complete",
                assignment_token=headers,
                payload={
                    "outcome": "failed",
                    "summary": "Runner не смог завершить этап.",
                    "error_code": type(exc).__name__.lower()[:80],
                    "error_message": "Локальная ошибка runner; подробности остаются на ПК владельца.",
                },
            )
        finally:
            # A worktree with changes is intentionally retained for owner review; an unchanged one is safe to remove.
            if worktree and self._is_clean_worktree(worktree):
                self._remove_worktree(worktree)

    def _run_codex(
        self, run: dict[str, Any], worktree: Path | None
    ) -> tuple[subprocess.CompletedProcess[str], bool]:
        role = str(run["role"])
        prompt = "\n\n".join(
            [
                ROLE_PROMPTS.get(role, "Выполни назначенную роль безопасно."),
                f"Цель владельца: {run['goal']}",
                f"Разрешённые действия: {', '.join(run.get('allowed_actions', [])) or 'только чтение'}.",
                "Работай через уже настроенный TaskManager MCP. Не раскрывай секреты, cookies или токены. "
                "Не отправляй внешние сообщения, не публикуй и не трать деньги без созданного server-side approval.",
            ]
        )
        command = [self.config.codex_command, "exec", "--full-auto", prompt]
        process = subprocess.Popen(
            command,
            cwd=str(worktree or Path(self.config.workspace_path)),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        while process.poll() is None:
            time.sleep(min(10, self.config.poll_seconds))
            self.client.request(
                "POST",
                f"/agent-runners/{self.config.runner_id}/heartbeat",
                payload={"version": "0.1.0"},
            )
            control = self.client.request(
                "GET", f"/agent-runners/{self.config.runner_id}/control"
            )
            if isinstance(control, dict) and str(run["id"]) in control.get("cancelled_run_ids", []):
                process.terminate()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                return subprocess.CompletedProcess(command, process.returncode), True
        return subprocess.CompletedProcess(command, process.returncode), False

    def _create_worktree(self, run_id: str) -> Path:
        root = Path(self.config.workspace_path).resolve()
        worktree_root = self._worktree_path(run_id).parent
        target = self._worktree_path(run_id)
        if target.parent != worktree_root:
            raise RuntimeError("Refusing an unsafe worktree path")
        worktree_root.mkdir(parents=True, exist_ok=True)
        branch = f"codex/agent-{run_id[:8]}"
        command = ["git", "worktree", "add", "-b", branch, str(target), "HEAD"]
        created = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
        if created.returncode:
            raise RuntimeError("Could not create a dedicated Git worktree")
        return target

    def _worktree_path(self, run_id: str) -> Path:
        root = Path(self.config.workspace_path).resolve()
        return ((root.parent / "TaskmanAgentWorktrees").resolve() / run_id).resolve()

    @staticmethod
    def _next_role(run: dict[str, Any]) -> str | None:
        role = str(run["role"])
        if role == "coordinator":
            return "researcher_developer"
        if role == "researcher_developer":
            return "tester"
        if role == "tester" and "code_preview" in run.get("allowed_actions", []):
            return "visual_reviewer"
        return None

    @staticmethod
    def _is_clean_worktree(path: Path) -> bool:
        result = subprocess.run(
            ["git", "status", "--porcelain"], cwd=path, capture_output=True, text=True, check=False
        )
        return result.returncode == 0 and not result.stdout.strip()

    def _remove_worktree(self, path: Path) -> None:
        root = Path(self.config.workspace_path).resolve()
        worktree_root = (root.parent / "TaskmanAgentWorktrees").resolve()
        if path.resolve().parent != worktree_root:
            raise RuntimeError("Refusing to remove a worktree outside TaskmanAgentWorktrees")
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(path)],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
