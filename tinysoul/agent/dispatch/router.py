"""Typed target and subscription routing for environment events."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from tinysoul.runtime.events import EnvironmentEvent


class EventRouterError(Exception):
    """Event router registration or dispatch contract failure."""


EventTarget = Callable[[EnvironmentEvent], Awaitable[bool]]


class EventRouter:
    """Route one accepted event to its target and matching subscriptions."""

    def __init__(self) -> None:
        self._targets: dict[str, EventTarget] = {}
        self._subscriptions: dict[str, tuple[str, Callable[[EnvironmentEvent], bool]]] = {}

    def register_target(self, target_id: str, target: EventTarget) -> None:
        if not target_id or not callable(target):
            raise EventRouterError("Event target registration is invalid")
        if target_id in self._targets:
            raise EventRouterError("Event target is already registered")
        self._targets[target_id] = target

    def unregister_target(self, target_id: str) -> None:
        self._targets.pop(target_id, None)
        self._subscriptions = {
            key: value for key, value in self._subscriptions.items()
            if value[0] != target_id
        }

    def subscribe(
        self, subscription_id: str, target_id: str,
        matches: Callable[[EnvironmentEvent], bool],
    ) -> None:
        if (
            not subscription_id
            or target_id not in self._targets
            or not callable(matches)
        ):
            raise EventRouterError("Event subscription is invalid")
        if subscription_id in self._subscriptions:
            raise EventRouterError("Event subscription is already registered")
        self._subscriptions[subscription_id] = (target_id, matches)

    def unsubscribe(self, subscription_id: str) -> None:
        self._subscriptions.pop(subscription_id, None)

    async def route(self, event: EnvironmentEvent) -> int:
        if not isinstance(event, EnvironmentEvent):
            raise EventRouterError("EventRouter accepts EnvironmentEvent only")
        targets: dict[str, EventTarget] = {}
        if event.target_id is not None:
            target = self._targets.get(event.target_id)
            if target is not None:
                targets[event.target_id] = target
        else:
            for target_id, matches in tuple(self._subscriptions.values()):
                if matches(event):
                    targets[target_id] = self._targets[target_id]
        delivered = 0
        for target in targets.values():
            delivered += int(await target(event))
        return delivered
