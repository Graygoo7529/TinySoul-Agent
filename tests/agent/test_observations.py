"""SDK observations are bounded side channels, including thread producers."""

import asyncio

import pytest

from tinysoul.agent import ObservationFilter, ObservationGap, ObservationRecord
from tinysoul.agent.errors import AgentClosedError, AgentSDKError
from tinysoul.agent.observations import ObservationSubscriptions
from tinysoul.agent.outputs import ObservationRouter
from tinysoul.runtime import ObservationEvent, ObservationLevel


def _event(text: str = "value", *, name: str = "changed") -> ObservationEvent:
    return ObservationEvent(name, ObservationLevel.NORMAL, "test", payload={"text": text})


async def test_slow_observer_gets_gap_and_newest_bounded_records() -> None:
    hub = ObservationSubscriptions()
    stream = hub.subscribe(capacity=2)
    for index in range(1000):
        hub.write(_event(str(index)))
    assert await anext(stream) == ObservationGap(1, 998, 998)
    retained = [await anext(stream), await anext(stream)]
    assert all(isinstance(item, ObservationRecord) for item in retained)
    assert [item.sequence for item in retained if isinstance(item, ObservationRecord)] == [999, 1000]
    hub.close()
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


async def test_bytes_filter_isolation_and_subscription_limit() -> None:
    hub = ObservationSubscriptions(max_subscribers=2)
    first = hub.subscribe(ObservationFilter(names=("changed",)), max_bytes=250)
    second = hub.subscribe()
    with pytest.raises(AgentSDKError, match="limit"):
        hub.subscribe()
    hub.write(_event("x" * 1000))
    assert await anext(first) == ObservationGap(1, 1, 1)
    await anext(second)
    hub.write(_event())
    left, right = await anext(first), await anext(second)
    assert isinstance(left, ObservationRecord) and isinstance(right, ObservationRecord)
    left.event.payload["text"] = "consumer mutation"
    assert right.event.payload == {"text": "value"}
    hub.write(_event(name="ignored"))
    await first.aclose()
    with pytest.raises(StopAsyncIteration):
        await anext(first)
    replacement = hub.subscribe()
    await replacement.aclose()
    hub.close()
    with pytest.raises(AgentClosedError):
        hub.subscribe()


async def test_thread_producer_wakes_reader_and_close_ends_pending_read() -> None:
    hub = ObservationSubscriptions()
    stream = hub.subscribe()
    reader = asyncio.create_task(anext(stream))
    await asyncio.to_thread(hub.write, _event())
    assert isinstance(await asyncio.wait_for(reader, 1), ObservationRecord)
    pending = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    hub.close()
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(pending, 1)


async def test_stream_serialization_failure_does_not_escape_observation_boundary() -> None:
    router = ObservationRouter()
    stream = router.subscriptions.subscribe()
    router.emit(_event("\ud800"))
    assert len(router.failures) == 1
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    router.emit(_event("still running"))
    assert len(router.failures) == 1
