"""Workspace read and write request schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from tinysoul.plugins.workspace import WorkspaceTag


class WorkspaceWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link: str = Field(min_length=1)
    text: str
    overwrite: bool = False


class WorkspaceTrashRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link: str = Field(min_length=1)


class WorkspaceRestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trash_ref: str = Field(min_length=1)


class WorkspaceDirectoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    link: str = Field(min_length=1)


class WorkspaceMoveRequest(WorkspaceDirectoryRequest):
    target_link: str = Field(min_length=1)


class WorkspaceTagRequest(WorkspaceDirectoryRequest):
    tags: list[WorkspaceTag] = Field(max_length=3)


class WorkspaceEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    old_text: str = Field(min_length=1)
    new_text: str


class WorkspaceEditRequest(WorkspaceDirectoryRequest):
    edits: list[WorkspaceEdit] = Field(min_length=1, max_length=64)


class WorkspaceAppendRequest(WorkspaceDirectoryRequest):
    text: str
