"""Typed target and subscription routing for environment events."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from tinysoul.runtime.events import EnvironmentEvent, EventKind


class EventRouterError(Exception):
    """Event router registration or dispatch contract failure."""


EventTarget = Callable[[EnvironmentEvent], Awaitable[bool]]


class EventRouter:
    """Route one accepted event to its target and matching subscriptions."""

    def __init__(self) -> None:
        self._targets: dict[str, EventTarget] = {}
        self._subscriptions: dict[EventKind, dict[str, EventTarget]] = {}

    def register_target(self, target_id: str, target: EventTarget) -> None:
        if not target_id or not callable(target):
            raise EventRouterError("Event target registration is invalid")
        if target_id in self._targets:
            raise EventRouterError("Event target is already registered")
        self._targets[target_id] = target

    def unregister_target(self, target_id: str) -> None:
        self._targets.pop(target_id, None)

    def subscribe(
        self, subscription_id: str, kind: EventKind, target: EventTarget
    ) -> None:
        if (
            not subscription_id
            or not isinstance(kind, EventKind)
            or not callable(target)
        ):
            raise EventRouterError("Event subscription is invalid")
        subscriptions = self._subscriptions.setdefault(kind, {})
        if subscription_id in subscriptions:
            raise EventRouterError("Event subscription is already registered")
        subscriptions[subscription_id] = target

    def unsubscribe(self, subscription_id: str) -> None:
        for subscriptions in self._subscriptions.values():
            subscriptions.pop(subscription_id, None)

    async def route(self, event: EnvironmentEvent) -> int:
        if not isinstance(event, EnvironmentEvent):
            raise EventRouterError("EventRouter accepts EnvironmentEvent only")
        targets: list[EventTarget] = []
        if event.target_id is not None:
            target = self._targets.get(event.target_id)
            if target is not None:
                targets.append(target)
        else:
            targets.extend(self._subscriptions.get(event.kind, {}).values())
        unique = {id(target): target for target in targets}
        delivered = 0
        for target in unique.values():
            delivered += int(await target(event))
        return delivered
