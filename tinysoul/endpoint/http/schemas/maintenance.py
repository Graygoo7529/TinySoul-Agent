"""Maintenance request schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tinysoul.infra.json import JsonValue


class MaintenanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["daily", "home", "memory"]
    target_day: str = ""
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    command_id: str = Field(default="", max_length=128)
