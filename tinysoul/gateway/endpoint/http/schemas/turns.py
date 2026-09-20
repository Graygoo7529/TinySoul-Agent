"""Structured Turn and Turn-owned Job protocol schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tinysoul.infra.json import JsonValue


class TurnCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["user", "home", "memory"] = "user"
    text: str = Field(default="", max_length=16000)
    target_day: str = ""
    instructions: str = Field(default="", max_length=16000)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    command_id: str = Field(default="", max_length=128)


class TurnInputRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    input_id: str = Field(default="", max_length=128)


class TurnReplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(min_length=1, max_length=128)
    response: str = Field(min_length=1, max_length=16000)


class TurnGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=128)
    count: int = Field(gt=0, strict=True)
