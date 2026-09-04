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

    def test_progress_reports_safe_agent_activity_without_private_reasoning(self):
        progress = LocalRunner._codex_progress({"type": "item.started", "item": {"type": "reasoning"}})
        self.assertEqual(progress, ("Агент анализирует задачу и уточняет план.", {"kind": "analysis"}))

        report = LocalRunner._codex_progress({"type": "item.completed", "item": {"type": "agent_message", "text": "Bearer sk-secret-value-12345678 готов"}})
        assert report is not None
        self.assertNotIn("secret-value", report[1]["text"])


if __name__ == "__main__":
    unittest.main()
