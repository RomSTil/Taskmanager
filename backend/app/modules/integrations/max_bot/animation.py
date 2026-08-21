import threading
import time

from .client import MaxApiClient
from .formatter import waiting_payload

FRAME_INTERVAL_SECONDS = 0.55
MINIMUM_VISIBLE_SECONDS = FRAME_INTERVAL_SECONDS * 2


class WaitingMessageAnimation:
    def __init__(
        self,
        client: MaxApiClient,
        message_id: str,
        action_label: str,
    ) -> None:
        self._client = client
        self._message_id = message_id
        self._action_label = action_label
        self._started_at = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._animate, daemon=True)

    def start(self) -> None:
        self._started_at = time.monotonic()
        self._thread.start()

    def finish(self) -> None:
        remaining = MINIMUM_VISIBLE_SECONDS - (time.monotonic() - self._started_at)
        if remaining > 0:
            time.sleep(remaining)
        self._stop.set()
        self._thread.join()
        try:
            self._client.delete_message(self._message_id)
        except Exception:  # noqa: BLE001
            # A failed cleanup must not turn a successful business action into an error.
            pass

    def _animate(self) -> None:
        dots = 1
        while not self._stop.wait(FRAME_INTERVAL_SECONDS):
            try:
                self._client.edit_message(
                    self._message_id,
                    waiting_payload(self._action_label, dots),
                )
            except Exception:  # noqa: BLE001
                return
            dots = (dots + 1) % 4
