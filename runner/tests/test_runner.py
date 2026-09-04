import unittest
from unittest.mock import patch

from taskman_agent_runner.config import RunnerConfig
from taskman_agent_runner.runner import LocalRunner


class _Process:
    returncode = 0

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
        self.assertEqual(command[command.index("--sandbox") + 1], "workspace-write")


if __name__ == "__main__":
    unittest.main()
