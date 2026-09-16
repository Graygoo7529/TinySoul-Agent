"""Input source contracts independent of Agent command dispatch."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4

from tinysoul.infra.json import JsonObject, to_json_object
from .errors import EnvironmentError


@dataclass(frozen=True)
class InputEvent:
    text: str
    source: str = "api"
    metadata: JsonObject = field(default_factory=dict)
    command_id: str = field(default_factory=lambda: f"command_{uuid4().hex}")

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise EnvironmentError("InputEvent.text must be a string")
        if not isinstance(self.source, str) or not self.source.strip():
            raise EnvironmentError("InputEvent.source must be non-empty")
        if not isinstance(self.command_id, str) or not self.command_id.strip():
            raise EnvironmentError("InputEvent.command_id must be non-empty")
        object.__setattr__(self, "source", self.source.strip())
        object.__setattr__(self, "metadata", to_json_object(self.metadata))
        object.__setattr__(self, "command_id", self.command_id.strip())


@dataclass(frozen=True)
class CommandReceipt:
    accepted: bool
    command_id: str
    kind: str
    state: str

    def to_json(self) -> JsonObject:
        return {
            "accepted": self.accepted,
            "command_id": self.command_id,
            "kind": self.kind,
            "state": self.state,
        }


class InputSink(Protocol):
    def submit(self, event: InputEvent) -> CommandReceipt: ...


class InputSource(Protocol):
    def start(self, sink: InputSink) -> None: ...

    def stop(self) -> None: ...
