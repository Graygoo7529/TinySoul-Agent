"""Configuration mutation and capability lookup schemas."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_core import PydanticCustomError

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


class ConfigCreateSourceMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1)
    op: Literal["create_source"]


ConfigMutationRequest = Annotated[
    ConfigSetMutationRequest
    | ConfigDeleteMutationRequest
    | ConfigCreateSourceMutationRequest,
    Field(discriminator="op"),
]


class ConfigPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operations: list[ConfigMutationRequest] = Field(min_length=1)


class ModelCapabilityLookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)


class ModelCapabilityChoicesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supported: bool
    choices: list[str]


class ModelCapabilityLookupResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str
    model_id: str
    display_name: str | None = None
    lifecycle: str | None = None
    max_input_tokens: int | None = None
    max_tokens: int | None = None
    thinking: ModelCapabilityChoicesResponse | None = None
    reasoning_effort: ModelCapabilityChoicesResponse | None = None


class ConfigApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operations: list[ConfigMutationRequest] | None = Field(default=None, min_length=1)
    preset_id: str | None = Field(default=None, min_length=1)

    def model_post_init(self, __context: object) -> None:
        if (self.operations is None) == (self.preset_id is None):
            raise PydanticCustomError(
                "apply_candidate",
                "Apply requires exactly one of operations or preset_id",
            )


class PresetCaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_budgets: bool = True


class PresetCreateRequest(PresetCaptureRequest):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class PresetUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    capture: PresetCaptureRequest | None = None
