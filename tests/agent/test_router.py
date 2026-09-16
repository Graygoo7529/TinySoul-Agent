from __future__ import annotations

from tinysoul.agent.router import EventRouter
from tinysoul.runtime.events import EnvironmentEvent, EventKind


async def test_target_and_subscription_share_one_delivery() -> None:
    router = EventRouter()
    received: list[str] = []

    async def target(event: EnvironmentEvent) -> bool:
        received.append(event.event_id)
        return True

    router.register_target("turn", target)
    router.subscribe("sub", EventKind.EVENT, target)
    assert await router.route(EnvironmentEvent(EventKind.EVENT, {}, "e", "turn")) == 1
    assert received == ["e"]
    assert await router.route(EnvironmentEvent(EventKind.EVENT, {}, "global")) == 1
    assert await router.route(EnvironmentEvent(EventKind.EVENT, {}, "stale", "old_turn")) == 0
    assert received == ["e", "global"]
