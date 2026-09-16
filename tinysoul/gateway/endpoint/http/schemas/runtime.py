"""Runtime command request schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tinysoul.infra.json import JsonValue


class InputRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    command_id: str = Field(default="", max_length=128)


class ControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["stop_turn", "exit_program"]
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    command_id: str = Field(default="", max_length=128)
