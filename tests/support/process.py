from __future__ import annotations

from collections.abc import Callable
from time import monotonic, sleep


PYTHON_WAIT_FOREVER = "import threading; threading.Event().wait()"


def wait_until(
    predicate: Callable[[], bool],
    *,
    timeout: float,
    interval: float = 0.01,
) -> None:
    """Wait for an observable test condition with one bounded deadline."""
    deadline = monotonic() + timeout
    while not predicate():
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise AssertionError("Timed out waiting for test condition")
        sleep(min(interval, remaining))
