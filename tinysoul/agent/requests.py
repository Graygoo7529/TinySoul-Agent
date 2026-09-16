"""Typed requests accepted by the top-level Program queue."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.plugins.reflection import (ReflectionRequest)

from .errors import AgentSDKError


@dataclass(frozen=True)
class UserTurnRequest:
    text: str
    source: str = ""
    request_id: str = field(default_factory=lambda: f"request_{uuid4().hex}")
    metadata: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise AgentSDKError("User Turn request text must be non-empty")
        if not isinstance(self.source, str):
            raise AgentSDKError("User Turn request source must be text")
        if not isinstance(self.request_id, str) or not self.request_id.strip():
            raise AgentSDKError("User Turn request_id must be non-empty")
        object.__setattr__(self, "text", self.text.strip())
        object.__setattr__(self, "request_id", self.request_id.strip())
        object.__setattr__(self, "metadata", to_json_object(self.metadata))


@dataclass(frozen=True)
class ExitRequest:
    text: str = ""
    source: str = ""
    request_id: str = field(default_factory=lambda: f"request_{uuid4().hex}")
    metadata: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not isinstance(self.source, str):
            raise AgentSDKError("Exit request text and source must be text")
        if not isinstance(self.request_id, str) or not self.request_id.strip():
            raise AgentSDKError("Exit request_id must be non-empty")
        object.__setattr__(self, "request_id", self.request_id.strip())
        object.__setattr__(self, "metadata", to_json_object(self.metadata))


AgentRequest = UserTurnRequest | ReflectionRequest | ExitRequest
