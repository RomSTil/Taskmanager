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
    "market_researcher": """Ты исследователь рынка. Найди не менее трёх независимых вариантов, а не три позиции одного продавца. Для каждого обязательно укажи: поставщика, точную ссылку на товар или карточку, цену и дату проверки, MOQ/минимальную партию либо честное «не указано», наличие/срок, доставку либо честное «не указано», а также публичный способ связи: телефон, email, форма или страница контактов. Сопоставь характеристики с целью владельца, отдели факты от предположений и выдай финальную рекомендацию «что брать, у кого и почему». Если подтверждённого контакта или условия нет, не выдумывай его. Сохрани итоговую таблицу и ссылки в TaskManager MCP.""",
    "researcher_developer": "Ты исследователь или разработчик. Выполни работу и фиксируй проверяемые результаты в TaskManager MCP.",
    "tester": "Ты тестировщик. Проверь критерии результата и верни воспроизводимые дефекты либо готовность к оценке владельца. Для исследования рынка не принимай результат без трёх независимых вариантов, ссылок, дат проверки, публичных контактов, условий поставки и ясной рекомендации.",
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
            self._progress(
                run_id,
                headers,
                f"Выбрана модель {self.config.codex_model}.",
                role=role,
                kind="model",
                model=self.config.codex_model,
                effort="automatic",
            )
            self._progress(run_id, headers, "Агент формирует план текущего этапа.", role=role, kind="plan")
            result, cancelled, clarification_requested = self._run_codex(run, worktree, headers)
            if cancelled:
                return
            if clarification_requested:
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
    ) -> tuple[subprocess.CompletedProcess[str], bool, bool]:
        role = str(run["role"])
        prompt = "\n\n".join(
            [
                ROLE_PROMPTS.get(role, "Выполни назначенную роль безопасно."),
                f"Цель владельца: {run['goal']}",
                f"Разрешённые действия: {', '.join(run.get('allowed_actions', [])) or 'только чтение'}.",
                "Если без решения владельца нельзя продолжать, задай один конкретный вопрос в отдельном финальном сообщении, начиная его с `ВОПРОС ВЛАДЕЛЬЦУ:`.",
                "Работай через уже настроенный TaskManager MCP. Не раскрывай секреты, cookies или токены. "
                "Не отправляй внешние сообщения, не публикуй и не трать деньги без созданного server-side approval.",
            ]
        )
        command = [
            self.config.codex_command,
            "exec",
            "--approve-for-me",
            "--json",
            "--model",
            self.config.codex_model,
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
                if self._record_codex_event(run, assignment_token, line):
                    process.terminate()
                    process.wait(timeout=20)
                    return subprocess.CompletedProcess(command, process.returncode), False, True
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
                return subprocess.CompletedProcess(command, process.returncode), True, False
        clarification_requested = False
        while not output.empty():
            clarification_requested = self._record_codex_event(
                run, assignment_token, output.get_nowait()
            ) or clarification_requested
        return subprocess.CompletedProcess(command, process.returncode), False, clarification_requested

    def _record_codex_event(self, run: dict[str, Any], assignment_token: str | None, line: str) -> bool:
        if not assignment_token:
            return False
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return False
        progress = self._codex_progress(event)
        if progress is None:
            return False
        summary, payload = progress
        event_type = "clarification_requested" if payload.get("kind") == "question" else "progress"
        self.client.request(
            "POST",
            f"/agent-runs/{run['id']}/events",
            assignment_token=assignment_token,
            payload={"event_type": event_type, "summary": summary, "payload": {"role": str(run["role"]), **payload}},
        )
        return event_type == "clarification_requested"

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
        if event_type == "turn.completed":
            usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
            input_tokens = int(usage.get("input_tokens") or 0)
            output_tokens = int(usage.get("output_tokens") or 0)
            reasoning_tokens = int(usage.get("reasoning_tokens") or 0)
            if any((input_tokens, output_tokens, reasoning_tokens)):
                return "Codex вернул фактический расход токенов.", {
                    "kind": "usage",
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "reasoning_tokens": reasoning_tokens,
                }
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
                if text.casefold().startswith("вопрос владельцу:"):
                    return text, {"kind": "question"}
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
            return "researcher_developer" if "code_preview" in run.get("allowed_actions", []) else "market_researcher"
        if role == "market_researcher":
            return "tester"
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
