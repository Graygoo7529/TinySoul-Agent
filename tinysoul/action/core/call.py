"""Action call and execution input models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from time import monotonic
from uuid import uuid4

from tinysoul.infra.json import JsonObject, JsonValue, to_json_object
from tinysoul.llm.tools import ToolCallRecord, ToolKind
from tinysoul.runtime import RunScope

from .catalog import ActionCatalog


@dataclass(frozen=True)
class ActionCall:
    """A normalized Phase2 action call."""

    call_id: str
    action_name: str
    params: JsonObject
    tool_call_id: str
    intent: str = ""

    def __post_init__(self) -> None:
        _require_non_empty(self.call_id, "ActionCall.call_id")
        _require_non_empty(self.action_name, "ActionCall.action_name")
        _require_non_empty(self.tool_call_id, "ActionCall.tool_call_id")
        object.__setattr__(self, "params", to_json_object(self.params))


@dataclass(frozen=True)
class ActionFramework:
    """Framework-only execution data for an action call."""

    invoke_id: str
    batch_id: str
    scope: RunScope
    domain: str
    deadline: float | None = None
    timeout_seconds: float | None = None
    turn_id: str = ""
    cycle_id: str = ""
    phase: str = "phase3"

    def __post_init__(self) -> None:
        _require_non_empty(self.invoke_id, "ActionFramework.invoke_id")
        _require_non_empty(self.batch_id, "ActionFramework.batch_id")
        _require_non_empty(self.domain, "ActionFramework.domain")
        if not isinstance(self.scope, RunScope):
            raise TypeError("ActionFramework.scope must be a RunScope")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("ActionFramework.timeout_seconds must be positive")

    def is_expired(self) -> bool:
        return self.deadline is not None and monotonic() >= self.deadline


@dataclass(frozen=True)
class ActionExecution:
    """A Phase3 execution wrapper around an action call."""

    call: ActionCall
    framework: ActionFramework


@dataclass(frozen=True)
class ActionBatch:
    """A batch of action executions scheduled together."""

    batch_id: str
    executions: tuple[ActionExecution, ...] = field(default_factory=tuple)
    deadline: float | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.batch_id, "ActionBatch.batch_id")
        for execution in self.executions:
            if execution.framework.batch_id != self.batch_id:
                raise ValueError("ActionExecution.framework.batch_id must match ActionBatch.batch_id")


class ActionCallNormalizer:
    """Normalize Phase2 tool calls into action calls."""

    def normalize(
        self,
        tool_calls: tuple[ToolCallRecord, ...],
        *,
        catalog: ActionCatalog,
    ) -> tuple[ActionCall, ...]:
        calls: list[ActionCall] = []
        for index, tool_call in enumerate(tool_calls):
            if tool_call.kind is not ToolKind.ACTION:
                raise ValueError(
                    f"Expected ACTION tool call for action normalization: {tool_call.name}"
                )
            if not catalog.has_action(tool_call.name):
                raise ValueError(f"Unknown action tool call: {tool_call.name}")
            action = catalog.get_action(tool_call.name)
            _validate_params(tool_call.arguments, schema=action.tool.schema)
            calls.append(
                ActionCall(
                    call_id=f"action_call_{index + 1}_{uuid4().hex[:8]}",
                    action_name=tool_call.name,
                    params=tool_call.arguments,
                    tool_call_id=tool_call.id,
                )
            )
        return tuple(calls)


class ActionExecutionBuilder:
    """Build execution inputs from normalized action calls."""

    def build_batch(
        self,
        calls: tuple[ActionCall, ...],
        *,
        catalog: ActionCatalog,
        scope: RunScope,
        batch_id: str | None = None,
        turn_id: str = "",
        cycle_id: str = "",
        phase: str = "phase3",
    ) -> ActionBatch:
        resolved_batch_id = batch_id or f"action_batch_{uuid4().hex[:8]}"
        executions: list[ActionExecution] = []
        deadlines: list[float] = []
        for call in calls:
            action = catalog.get_action(call.action_name)
            timeout = action.runtime.timeout_seconds
            deadline = monotonic() + timeout if timeout is not None else None
            if deadline is not None:
                deadlines.append(deadline)
            executions.append(
                ActionExecution(
                    call=call,
                    framework=ActionFramework(
                        invoke_id=f"action_invoke_{uuid4().hex[:8]}",
                        batch_id=resolved_batch_id,
                        scope=scope,
                        domain=action.domain,
                        deadline=deadline,
                        timeout_seconds=timeout,
                        turn_id=turn_id,
                        cycle_id=cycle_id,
                        phase=phase,
                    ),
                )
            )
        batch_deadline = min(deadlines) if deadlines else None
        return ActionBatch(
            batch_id=resolved_batch_id,
            executions=tuple(executions),
            deadline=batch_deadline,
        )


def _require_non_empty(value: str, field: str) -> None:
    if not value:
        raise ValueError(f"{field} must be non-empty")


def _validate_params(params: JsonObject, *, schema: JsonObject) -> None:
    schema_type = schema.get("type")
    if schema_type is not None and schema_type != "object":
        raise ValueError("Action tool schema root type must be object")

    required = schema.get("required", [])
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise ValueError("Action tool schema required must be a list of strings")
    for name in required:
        if name not in params:
            raise ValueError(f"Missing required action parameter: {name}")

    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise ValueError("Action tool schema properties must be an object")

    if schema.get("additionalProperties") is False:
        for name in params:
            if name not in properties:
                raise ValueError(f"Unexpected action parameter: {name}")

    for name, value in params.items():
        property_schema = properties.get(name)
        if isinstance(property_schema, dict):
            _validate_json_type(name, value, schema=property_schema)


def _validate_json_type(
    name: str,
    value: JsonValue,
    *,
    schema: Mapping[str, JsonValue],
) -> None:
    expected_type = schema.get("type")
    if expected_type is None:
        return
    if not isinstance(expected_type, str):
        raise ValueError(f"Action parameter schema type for {name} must be a string")
    if not _matches_json_type(value, expected_type):
        raise ValueError(f"Action parameter {name} must be {expected_type}")


def _matches_json_type(value: JsonValue, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "number":
        return (isinstance(value, int | float) and not isinstance(value, bool))
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "null":
        return value is None
    raise ValueError(f"Unsupported action parameter schema type: {expected_type}")
