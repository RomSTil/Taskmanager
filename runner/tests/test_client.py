import unittest
from unittest.mock import patch

from taskman_agent_runner.client import TaskmanClient


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return b'{"status":"ready"}'


class TaskmanClientTests(unittest.TestCase):
    @patch("taskman_agent_runner.client.urlopen", return_value=_Response())
    def test_request_uses_certifi_backed_tls_context(self, mock_urlopen):
        result = TaskmanClient("https://api.example").request("GET", "/readyz")

        self.assertEqual(result, {"status": "ready"})
        self.assertIsNotNone(mock_urlopen.call_args.kwargs["context"])


if __name__ == "__main__":
    unittest.main()
