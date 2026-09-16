from __future__ import annotations

import pytest

from tinysoul.runtime.events import EnvironmentEvent, EventBus, EventKind, EventProtocolError


async def test_delivery_failure_can_retry_and_completed_identity_is_idempotent() -> None:
    bus = EventBus(capacity=2)
    event = EnvironmentEvent(EventKind.EVENT, {"value": 1}, event_id="e")
    attempts = 0

    async def deliver(value: EnvironmentEvent) -> int:
        nonlocal attempts
        assert value == event
        attempts += 1
        if attempts == 1:
            raise EventProtocolError("target admission failed")
        return 1

    with pytest.raises(EventProtocolError):
        await bus.publish(event, deliver=deliver)
    accepted = await bus.publish(event, deliver=deliver)
    duplicate = await bus.publish(event, deliver=deliver)
    assert accepted.delivered and not duplicate.delivered
    assert accepted.sequence == duplicate.sequence
    assert attempts == 2
    with pytest.raises(EventProtocolError):
        await bus.publish(EnvironmentEvent(EventKind.EVENT, {"value": 2}, event_id="e"), deliver=deliver)
