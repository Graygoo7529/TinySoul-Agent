"""TinySoul model-side tool semantics."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from tinysoul.infra.json import JsonObject, to_json_object


class ToolKind(StrEnum):
    """TinySoul model-side tool category."""

    CONTROL = "control"
    ACTION = "action"


class ToolUse(StrEnum):
    """Tool use policy for a model call."""

    DISABLED = "disabled"
    OPTIONAL = "optional"
    REQUIRED = "required"


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
class ToolSelection:
    """Tool selection constraints prepared by the caller."""

    allowed_names: tuple[str, ...] = ()
    forced_name: str | None = None

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for name in self.allowed_names:
            _require_name(name, field="ToolSelection.allowed_names")
            if name in seen:
                raise ValueError(f"Duplicate tool selection name: {name}")
            seen.add(name)
        if self.forced_name is not None:
            _require_name(self.forced_name, field="ToolSelection.forced_name")
            if self.allowed_names and self.forced_name not in seen:
                raise ValueError("ToolSelection.forced_name must be in allowed_names")


@dataclass(frozen=True)
class ToolScope:
    """Tools visible to a model call plus selection constraints."""

    tools: tuple[ToolSpec, ...] = field(default_factory=tuple)
    selection: ToolSelection = field(default_factory=ToolSelection)

    def __post_init__(self) -> None:
        names = {tool.name for tool in self.tools}
        missing_allowed = [
            name for name in self.selection.allowed_names if name not in names
        ]
        if missing_allowed:
            raise ValueError(f"Unknown tool selection name: {missing_allowed[0]}")
        if (
            self.selection.forced_name is not None
            and self.selection.forced_name not in names
        ):
            raise ValueError(
                f"Unknown forced tool name: {self.selection.forced_name}"
            )


@dataclass(frozen=True)
class ToolCallRecord:
    """A TinySoul-normalized model-side tool call."""

    id: str
    name: str
    arguments: JsonObject
    kind: ToolKind | None = None

    def __post_init__(self) -> None:
        _require_name(self.id, field="ToolCallRecord.id")
        _require_name(self.name, field="ToolCallRecord.name")
        object.__setattr__(self, "arguments", to_json_object(self.arguments))


class ToolCallIdMapper:
    """Map between TinySoul and provider tool call ids."""

    def to_tinysoul_id(
        self,
        provider_call_id: str | None,
        *,
        index: int,
        tool_name: str,
    ) -> str:
        """Return a TinySoul tool call id for a provider call."""
        raise NotImplementedError

    def to_provider_id(self, tinysoul_id: str) -> str:
        """Return a provider call id for a TinySoul call id."""
        raise NotImplementedError


class DefaultToolCallIdMapper(ToolCallIdMapper):
    """Provider-friendly id mapping that keeps valid provider ids."""

    def to_tinysoul_id(
        self,
        provider_call_id: str | None,
        *,
        index: int,
        tool_name: str,
    ) -> str:
        if provider_call_id and _valid_tool_call_id(provider_call_id):
            return provider_call_id
        safe_tool_name = "".join(
            char if char.isalnum() or char in {"_", "-"} else "_"
            for char in tool_name
        )
        if not safe_tool_name or not (
            safe_tool_name[0].isalpha() or safe_tool_name[0] == "_"
        ):
            safe_tool_name = f"tool_{safe_tool_name}"
        return f"{safe_tool_name}_{index + 1}"

    def to_provider_id(self, tinysoul_id: str) -> str:
        _require_name(tinysoul_id, field="tinysoul_id")
        return tinysoul_id


def _require_name(value: str, *, field: str) -> None:
    if not value:
        raise ValueError(f"{field} must be non-empty")


def _valid_tool_call_id(value: str) -> bool:
    if not value:
        return False
    first = value[0]
    if not (first.isalpha() or first == "_"):
        return False
    return all(char.isalnum() or char in {"_", "-"} for char in value)
