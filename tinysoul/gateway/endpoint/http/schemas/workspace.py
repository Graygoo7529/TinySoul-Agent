"""Workspace read and write request schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link: str = Field(min_length=1)
    text: str
    overwrite: bool = False
    expected_digest: str = ""
    expected_revision: int = Field(ge=0)
    retention: Literal["ephemeral", "turn", "day", "persistent"] | None = None


class WorkspaceTrashRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link: str = Field(min_length=1)
    expected_digest: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)


class WorkspaceRestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trash_ref: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)
