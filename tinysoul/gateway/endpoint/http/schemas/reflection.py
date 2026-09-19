"""Reflection request schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tinysoul.infra.json import JsonValue


class ReflectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["home", "memory"]
    target_day: str = ""
    instructions: str = Field(default="", max_length=16000)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    command_id: str = Field(default="", max_length=128)
