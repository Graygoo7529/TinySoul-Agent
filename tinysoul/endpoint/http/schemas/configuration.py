"""Configuration mutation request schemas."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from tinysoul.infra.config import ConfigValue


class ConfigSetMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    op: Literal["set"]
    value: ConfigValue


class ConfigDeleteMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    op: Literal["delete"]


ConfigMutationRequest = Annotated[
    ConfigSetMutationRequest | ConfigDeleteMutationRequest,
    Field(discriminator="op"),
]


class ConfigPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operations: list[ConfigMutationRequest] = Field(min_length=1)
