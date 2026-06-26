"""TinySoul model-side tool semantics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from tinysoul.infra.json import JsonObject, to_json_object


class ToolKind(StrEnum):
    """TinySoul model-side tool category."""

    CONTROL = "control"
    ACTION = "action"


class ToolChoiceMode(StrEnum):
    """Tool selection mode for a model call."""

    AUTO = "auto"
    REQUIRED = "required"
    NONE = "none"


class ToolResultStatus(StrEnum):
    """Tool result status for model-side replay."""

    OK = "ok"
    ERROR = "error"


@dataclass(frozen=True)
class ToolSpec:
    """A model-visible tool definition."""

    name: str
    description: str
    parameters: JsonObject
    kind: ToolKind
    strict: bool | None = None

    def __post_init__(self) -> None:
        _require_name(self.name, field="ToolSpec.name")
        if not self.description:
            raise ValueError("ToolSpec.description must be non-empty")
        object.__setattr__(self, "parameters", to_json_object(self.parameters))


@dataclass(frozen=True)
class ToolChoice:
    """Tool selection constraints for a model call."""

    mode: ToolChoiceMode
    allowed_names: tuple[str, ...] = ()
    forced_name: str | None = None

    def __post_init__(self) -> None:
        for name in self.allowed_names:
            _require_name(name, field="ToolChoice.allowed_names")
        if self.forced_name is not None:
            _require_name(self.forced_name, field="ToolChoice.forced_name")
        if self.mode is ToolChoiceMode.NONE:
            if self.allowed_names or self.forced_name is not None:
                raise ValueError("ToolChoice.NONE cannot constrain tool names")
        if self.mode is not ToolChoiceMode.REQUIRED and self.forced_name is not None:
            raise ValueError("ToolChoice.forced_name requires REQUIRED mode")

    @classmethod
    def auto(cls, *allowed_names: str) -> "ToolChoice":
        return cls(mode=ToolChoiceMode.AUTO, allowed_names=tuple(allowed_names))

    @classmethod
    def required(
        cls,
        *,
        forced_name: str | None = None,
        allowed_names: tuple[str, ...] = (),
    ) -> "ToolChoice":
        return cls(
            mode=ToolChoiceMode.REQUIRED,
            allowed_names=allowed_names,
            forced_name=forced_name,
        )

    @classmethod
    def none(cls) -> "ToolChoice":
        return cls(mode=ToolChoiceMode.NONE)


@dataclass(frozen=True)
class ToolCallRecord:
    """A TinySoul-normalized model-side tool call."""

    id: str
    name: str
    arguments: JsonObject
    kind: ToolKind | None = None
    provider_call_id: str | None = None
    raw_provider_payload: JsonObject | None = None

    def __post_init__(self) -> None:
        _require_name(self.id, field="ToolCallRecord.id")
        _require_name(self.name, field="ToolCallRecord.name")
        object.__setattr__(self, "arguments", to_json_object(self.arguments))
        if self.provider_call_id is not None:
            _require_name(
                self.provider_call_id,
                field="ToolCallRecord.provider_call_id",
            )
        if self.raw_provider_payload is not None:
            object.__setattr__(
                self,
                "raw_provider_payload",
                to_json_object(self.raw_provider_payload),
            )


def _require_name(value: str, *, field: str) -> None:
    if not value:
        raise ValueError(f"{field} must be non-empty")
