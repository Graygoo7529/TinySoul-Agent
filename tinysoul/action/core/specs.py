"""Action catalog specification models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from tinysoul.infra.json import JsonObject, to_json_object

from .errors import ActionInvariantError
from .schema import validate_action_schema_definition


class ActionEnvironmentEffect(StrEnum):
    """Model-visible action environment effect."""

    READ_ONLY = "read_only"
    ADDITIVE = "additive"
    MODIFYING = "modifying"


class ActionParallelPolicy(StrEnum):
    """Framework execution policy for a single action."""

    ALLOWED = "allowed"
    SERIAL = "serial"


class ActionBackendKind(StrEnum):
    """Supported action execution backends."""

    NATIVE = "native"
    SUBPROCESS = "subprocess"
    SCRIPT = "script"
    LLM_STEP = "llm_step"


@dataclass(frozen=True)
class ActionDomainSpec:
    """A thin Phase1-visible action domain description."""

    name: str
    description: str
    selection_hint: str = ""

    def __post_init__(self) -> None:
        _require_name(self.name, field="ActionDomainSpec.name")
        if not self.description:
            raise ActionInvariantError("ActionDomainSpec.description must be non-empty")


@dataclass(frozen=True)
class ActionToolSpec:
    """Phase2 tool-call schema for an action."""

    name: str
    description: str
    schema: JsonObject

    def __post_init__(self) -> None:
        _require_name(self.name, field="ActionToolSpec.name")
        if not self.description:
            raise ActionInvariantError("ActionToolSpec.description must be non-empty")
        schema = to_json_object(self.schema)
        validate_action_schema_definition(
            schema,
            key=f"ActionToolSpec({self.name}).schema",
        )
        object.__setattr__(self, "schema", schema)


@dataclass(frozen=True)
class ActionSemanticSpec:
    """Phase2 model-visible semantic hints beyond the tool schema."""

    use_when: tuple[str, ...] = field(default_factory=tuple)
    avoid_when: tuple[str, ...] = field(default_factory=tuple)
    effects: tuple[ActionEnvironmentEffect, ...] = field(default_factory=tuple)
    examples: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "use_when",
            _str_tuple(self.use_when, "ActionSemanticSpec.use_when"),
        )
        object.__setattr__(
            self,
            "avoid_when",
            _str_tuple(self.avoid_when, "ActionSemanticSpec.avoid_when"),
        )
        object.__setattr__(
            self,
            "examples",
            _str_tuple(self.examples, "ActionSemanticSpec.examples"),
        )
        for effect in self.effects:
            if not isinstance(effect, ActionEnvironmentEffect):
                raise ActionInvariantError(
                    "ActionSemanticSpec.effects must contain ActionEnvironmentEffect values"
                )
        object.__setattr__(self, "effects", tuple(self.effects))


@dataclass(frozen=True)
class ActionHookSpec:
    """Framework-only action hook configuration split by lifecycle stage."""

    normalize_hooks: tuple[str, ...] = field(default_factory=tuple)
    execution_hooks: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "normalize_hooks",
            _str_tuple(self.normalize_hooks, "ActionHookSpec.normalize_hooks"),
        )
        object.__setattr__(
            self,
            "execution_hooks",
            _str_tuple(self.execution_hooks, "ActionHookSpec.execution_hooks"),
        )


@dataclass(frozen=True)
class ActionRuntimeSpec:
    """Framework-only action runtime configuration."""

    timeout_seconds: float | None = None
    parallel_policy: ActionParallelPolicy = ActionParallelPolicy.ALLOWED
    hooks: ActionHookSpec = field(default_factory=ActionHookSpec)
    requires: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ActionInvariantError("ActionRuntimeSpec.timeout_seconds must be positive")
        if not isinstance(self.parallel_policy, ActionParallelPolicy):
            raise ActionInvariantError(
                "ActionRuntimeSpec.parallel_policy must be an ActionParallelPolicy"
            )
        if not isinstance(self.hooks, ActionHookSpec):
            raise ActionInvariantError("ActionRuntimeSpec.hooks must be an ActionHookSpec")
        object.__setattr__(
            self,
            "requires",
            _str_tuple(self.requires, "ActionRuntimeSpec.requires"),
        )


@dataclass(frozen=True)
class ActionBackendSpec:
    """Framework-only action execution backend configuration."""

    kind: ActionBackendKind
    handler: str
    options: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ActionBackendKind):
            raise ActionInvariantError("ActionBackendSpec.kind must be an ActionBackendKind")
        _require_name(self.handler, field="ActionBackendSpec.handler")
        object.__setattr__(self, "options", to_json_object(self.options))


@dataclass(frozen=True)
class ActionSpec:
    """A complete action definition loaded from catalog TOML."""

    name: str
    domain: str
    tool: ActionToolSpec
    semantic: ActionSemanticSpec
    runtime: ActionRuntimeSpec
    backend: ActionBackendSpec

    def __post_init__(self) -> None:
        _require_name(self.name, field="ActionSpec.name")
        _require_name(self.domain, field="ActionSpec.domain")
        if self.tool.name != self.name:
            raise ActionInvariantError("ActionSpec.tool.name must match ActionSpec.name")


def _require_name(value: str, *, field: str) -> None:
    if not value:
        raise ActionInvariantError(f"{field} must be non-empty")


def _str_tuple(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value:
            raise ActionInvariantError(f"{field} must contain non-empty strings")
        result.append(value)
    return tuple(result)
