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

async def settled_process(manager, turn_id, observation):
    """Observe backend completion without recreating a production wait loop."""
    import asyncio
    from tinysoul.infra.concurrency import JoinedOperations
    from tinysoul.kernel.jobs import JobState
    from tinysoul.plugins.capabilities.supervised_process import SupervisedProcessObservation

    job_id = str(observation.payload["execution_id"])
    async with asyncio.timeout(10):
        while manager.registry.snapshot(turn_id, job_id).state is JobState.RUNNING:
            await asyncio.sleep(0.01)
    status = await manager.registry.describe(turn_id, job_id, operations=JoinedOperations())
    payload = status["details"]
    for stream in ("stdout", "stderr"):
        previous, current = observation.payload.get(stream), payload.get(stream)
        if isinstance(previous, dict) and isinstance(current, dict):
            current["text"] = str(previous.get("text", "")) + str(current.get("text", ""))
    return SupervisedProcessObservation(
        payload=payload, timed_out=payload["job_state"] == "timed_out",
        failed=payload["job_state"] == "failed",
    )
