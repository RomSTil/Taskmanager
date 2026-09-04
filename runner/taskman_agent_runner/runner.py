import json
import queue
import re
import subprocess
import threading
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
            payload={
                "event_type": "role_started",
                "summary": f"Роль запущена: {ROLE_PROMPTS.get(role, role).split('.')[0]}.",
                "payload": {"role": role, "kind": "role"},
            },
        )
        worktree: Path | None = None
        try:
            if role == "researcher_developer" and "code_preview" in run.get("allowed_actions", []):
                worktree = self._create_worktree(run_id)
            elif "code_preview" in run.get("allowed_actions", []):
                existing = self._worktree_path(run_id)
                if existing.exists():
                    worktree = existing
            self._progress(run_id, headers, "Агент формирует план текущего этапа.", role=role, kind="plan")
            result, cancelled = self._run_codex(run, worktree, headers)
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
        self, run: dict[str, Any], worktree: Path | None, assignment_token: str | None = None
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
        command = [
            self.config.codex_command,
            "exec",
            "--approve-for-me",
            "--json",
            prompt,
        ]
        process = subprocess.Popen(
            command,
            cwd=str(worktree or Path(self.config.workspace_path)),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        output: queue.Queue[str] = queue.Queue()

        def collect_output() -> None:
            if process.stdout is None:
                return
            for line in process.stdout:
                output.put(line)

        threading.Thread(target=collect_output, daemon=True).start()
        while process.poll() is None:
            try:
                line = output.get(timeout=min(10, self.config.poll_seconds))
                self._record_codex_event(run, assignment_token, line)
            except queue.Empty:
                pass
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
        while not output.empty():
            self._record_codex_event(run, assignment_token, output.get_nowait())
        return subprocess.CompletedProcess(command, process.returncode), False

    def _record_codex_event(self, run: dict[str, Any], assignment_token: str | None, line: str) -> None:
        if not assignment_token:
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return
        progress = self._codex_progress(event)
        if progress is None:
            return
        summary, payload = progress
        self._progress(str(run["id"]), assignment_token, summary, role=str(run["role"]), **payload)

    def _progress(self, run_id: str, assignment_token: str, summary: str, *, role: str, **payload: Any) -> None:
        self.client.request(
            "POST",
            f"/agent-runs/{run_id}/events",
            assignment_token=assignment_token,
            payload={"event_type": "progress", "summary": summary, "payload": {"role": role, **payload}},
        )

    @staticmethod
    def _codex_progress(event: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        event_type = str(event.get("type") or "")
        item = event.get("item")
        item_type = str(item.get("type") or "") if isinstance(item, dict) else ""
        if event_type == "turn.started":
            return "Агент приступил к анализу контекста.", {"kind": "analysis"}
        if event_type == "item.started" and item_type == "reasoning":
            return "Агент анализирует задачу и уточняет план.", {"kind": "analysis"}
        if event_type == "item.started" and item_type == "command_execution":
            return "Агент выполняет проверку в рабочем окружении.", {"kind": "action"}
        if event_type == "item.started" and item_type == "mcp_tool_call":
            return "Агент обращается к инструменту TaskManager.", {"kind": "mcp"}
        if event_type == "item.completed" and item_type == "command_execution":
            return "Проверка в рабочем окружении завершена.", {"kind": "action_complete"}
        if event_type == "item.completed" and item_type == "mcp_tool_call":
            return "Инструмент TaskManager вернул результат.", {"kind": "mcp_complete"}
        if event_type == "item.completed" and item_type == "agent_message":
            text = LocalRunner._safe_text(str(item.get("text") or ""))
            if text:
                return "Промежуточный вывод агента.", {"kind": "report", "text": text[:1_200]}
        return None

    @staticmethod
    def _safe_text(value: str) -> str:
        compact = " ".join(value.split())
        return re.sub(r"(?i)(bearer\\s+|tm_|sk-|y0_)[A-Za-z0-9_-]{8,}", r"\\1[скрыто]", compact)

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
