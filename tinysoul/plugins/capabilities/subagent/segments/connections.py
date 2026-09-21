"""Refresh a Working State projection only through a captured Context batch."""

from dataclasses import dataclass

from tinysoul.infra.json import JsonObject
from tinysoul.kernel.context.segments import (
    SegmentDescriptor,
    SegmentRegistration,
    SegmentSlot,
    TurnInfo,
)
from tinysoul.llm.protocol.messages import Message, UserMessage
from tinysoul.runtime import RunScope, Signal
from tinysoul.runtime.events import EnvironmentEvent
from ..engine import SubagentEngine


@dataclass(frozen=True)
class ConnectionsRefresh:
    pass


class ConnectionsSegment:
    def __init__(self, engine: SubagentEngine, turn_id: str) -> None:
        self._engine, self._turn_id = engine, turn_id
        self._snapshot: JsonObject = engine.connections(turn_id)

    async def prepare(self, updates: tuple[ConnectionsRefresh, ...]) -> JsonObject:
        return self._engine.connections(self._turn_id) if updates else self._snapshot

    def install(self, prepared: JsonObject) -> None:
        self._snapshot = prepared

    def seal(self) -> JsonObject:
        return self._snapshot

    def render(self) -> tuple[Message, ...]:
        return (
            (UserMessage.from_json(self._snapshot, label="connections"),)
            if self._snapshot.get("connections")
            else ()
        )

    async def close(self) -> None:
        self._snapshot = {"connections": []}


class ConnectionsProvider:
    def __init__(self, engine: SubagentEngine) -> None:
        self._engine = engine

    async def open(self, info: TurnInfo) -> ConnectionsSegment:
        return ConnectionsSegment(self._engine, info.turn_id)


def connection_refresh(event: EnvironmentEvent, scope: RunScope) -> tuple[Signal, ...]:
    return (Signal("context.connections", source="subagent", scope=scope, payload={}),)


def connections_registration(
    engine: SubagentEngine,
) -> SegmentRegistration[ConnectionsRefresh, JsonObject]:
    return SegmentRegistration(
        descriptor=SegmentDescriptor(
            "connections", "subagent", SegmentSlot.WORKING, 40
        ),
        provider=ConnectionsProvider(engine),
        signal_name="context.connections",
        update_type=ConnectionsRefresh,
        decode=lambda signal: ConnectionsRefresh(),
    )
