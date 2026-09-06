import unittest
from unittest.mock import patch

from taskman_agent_runner.config import RunnerConfig
from taskman_agent_runner.runner import LocalRunner


class _Process:
    returncode = 0
    stdout = None

    def poll(self):
        return self.returncode


class RunnerTests(unittest.TestCase):
    @patch("taskman_agent_runner.runner.subprocess.Popen", return_value=_Process())
    def test_uses_supported_noninteractive_codex_flags(self, popen):
        runner = LocalRunner(
            RunnerConfig("https://api.example", "runner", "C:\\workspace"), "runner-token"
        )

        runner._run_codex({"role": "coordinator", "goal": "Проверить запуск"}, None)

        command = popen.call_args.args[0]
        self.assertEqual(command[0:2], ["codex", "exec"])
        self.assertIn("--approve-for-me", command)
        self.assertIn("--json", command)
        self.assertNotIn("--sandbox", command)
        self.assertEqual(popen.call_args.kwargs["encoding"], "utf-8")
        self.assertEqual(popen.call_args.kwargs["errors"], "replace")

    def test_progress_reports_safe_agent_activity_without_private_reasoning(self):
        progress = LocalRunner._codex_progress({"type": "item.started", "item": {"type": "reasoning"}})
        self.assertEqual(progress, ("Агент анализирует задачу и уточняет план.", {"kind": "analysis"}))

        report = LocalRunner._codex_progress({"type": "item.completed", "item": {"type": "agent_message", "text": "Bearer sk-secret-value-12345678 готов"}})
        assert report is not None
        self.assertNotIn("secret-value", report[1]["text"])

    def test_market_researcher_is_required_for_non_code_research(self):
        self.assertEqual(
            LocalRunner._next_role({"role": "coordinator", "allowed_actions": ["research", "browser"]}),
            "market_researcher",
        )
        self.assertEqual(
            LocalRunner._next_role({"role": "market_researcher", "allowed_actions": ["research"]}),
            "tester",
        )

    def test_model_is_routed_by_complexity_unless_owner_overrides(self):
        automatic = LocalRunner(RunnerConfig("https://api.example", "runner", "C:\\workspace"), "runner-token")
        self.assertEqual(
            automatic._select_model({"mode": "auto", "allowed_actions": ["research", "browser"], "goal": "Найти поставщиков"})[0],
            "gpt-5.6-sol",
        )
        self.assertEqual(
            automatic._select_model({"mode": "maximum", "allowed_actions": [], "goal": "Проверить"})[0],
            "gpt-6-astra",
        )
        forced = LocalRunner(RunnerConfig("https://api.example", "runner", "C:\\workspace", codex_model="gpt-6-astra"), "runner-token")
        self.assertEqual(forced._select_model({"mode": "fast", "allowed_actions": [], "goal": "Проверить"})[0], "gpt-6-astra")


if __name__ == "__main__":
    unittest.main()
