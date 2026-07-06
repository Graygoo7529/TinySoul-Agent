"""Action call and execution input models."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from uuid import uuid4

from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.llm.tools import ToolCallRecord, ToolKind
from tinysoul.runtime import RunScope

from .catalog import ActionCatalog
from .errors import ActionContractError, ActionInvariantError
from .hooks import (
    ActionNormalizeHookPipeline,
    ActionNormalizeInput,
)
from .phase import ActionCyclePhase
from .result import ActionPhaseResult, ActionPhaseResultStage, ActionResult, ActionResultStage
from .specs import ActionSpec


@dataclass(frozen=True)
class ActionCall:
    """A normalized Phase2 action call."""

    call_id: str
    action_name: str
    params: JsonObject
    sequence: int

    def __post_init__(self) -> None:
        _require_non_empty(self.call_id, "ActionCall.call_id")
        _require_non_empty(self.action_name, "ActionCall.action_name")
        if self.sequence <= 0:
            raise ActionInvariantError("ActionCall.sequence must be positive")
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
    phase: ActionCyclePhase = ActionCyclePhase.PHASE3

    def __post_init__(self) -> None:
        _require_non_empty(self.invoke_id, "ActionFramework.invoke_id")
        _require_non_empty(self.batch_id, "ActionFramework.batch_id")
        _require_non_empty(self.domain, "ActionFramework.domain")
        if not isinstance(self.scope, RunScope):
            raise ActionInvariantError("ActionFramework.scope must be a RunScope")
        if not isinstance(self.phase, ActionCyclePhase):
            raise ActionInvariantError("ActionFramework.phase must be an ActionCyclePhase")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ActionInvariantError("ActionFramework.timeout_seconds must be positive")

    def is_expired(self) -> bool:
        return self.deadline is not None and monotonic() >= self.deadline


@dataclass(frozen=True)
class ActionExecution:
    """A Phase3 execution wrapper around an action call."""

    action: ActionSpec
    call: ActionCall
    framework: ActionFramework

    def __post_init__(self) -> None:
        if not isinstance(self.action, ActionSpec):
            raise ActionInvariantError("ActionExecution.action must be an ActionSpec")
        if self.action.name != self.call.action_name:
            raise ActionInvariantError("ActionExecution.action.name must match ActionCall.action_name")
        if self.action.domain != self.framework.domain:
            raise ActionInvariantError("ActionExecution.action.domain must match ActionFramework.domain")


@dataclass(frozen=True)
class ActionBatch:
    """A batch of action executions scheduled together."""

    batch_id: str
    executions: tuple[ActionExecution, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _require_non_empty(self.batch_id, "ActionBatch.batch_id")
        seen_call_ids: set[str] = set()
        seen_invoke_ids: set[str] = set()
        seen_sequences: set[int] = set()
        for execution in self.executions:
            if execution.framework.batch_id != self.batch_id:
                raise ActionInvariantError(
                    "ActionExecution.framework.batch_id must match ActionBatch.batch_id"
                )
            if execution.call.call_id in seen_call_ids:
                raise ActionInvariantError(
                    f"Duplicate action call id in batch: {execution.call.call_id}"
                )
            if execution.framework.invoke_id in seen_invoke_ids:
                raise ActionInvariantError(
                    f"Duplicate action invoke id in batch: {execution.framework.invoke_id}"
                )
            if execution.call.sequence in seen_sequences:
                raise ActionInvariantError(
                    f"Duplicate action sequence in batch: {execution.call.sequence}"
                )
            seen_call_ids.add(execution.call.call_id)
            seen_invoke_ids.add(execution.framework.invoke_id)
            seen_sequences.add(execution.call.sequence)


@dataclass(frozen=True)
class ActionNormalization:
    """Normalized Phase2 action calls plus local normalization failures."""

    calls: tuple[ActionCall, ...] = field(default_factory=tuple)
    results: tuple[ActionResult, ...] = field(default_factory=tuple)

    def merged_results(
        self,
        execution_results: tuple[ActionResult, ...],
    ) -> tuple[ActionResult, ...]:
        """Return normalization and execution results in original call order."""

        return tuple(
            sorted(
                (*self.results, *execution_results),
                key=lambda result: result.sequence,
            )
        )


class ActionCallNormalizer:
    """Normalize Phase2 tool calls into action calls."""

    def __init__(self, hooks: ActionNormalizeHookPipeline | None = None) -> None:
        self._hooks = hooks or ActionNormalizeHookPipeline()

    def normalize(
        self,
        tool_calls: tuple[ToolCallRecord, ...],
        *,
        catalog: ActionCatalog,
    ) -> ActionNormalization:
        calls: list[ActionCall] = []
        results: list[ActionResult] = []
        seen_call_ids: set[str] = set()
        for index, tool_call in enumerate(tool_calls):
            sequence = index + 1
            if tool_call.id in seen_call_ids:
                results.append(
                    _normalize_failure(
                        tool_call,
                        sequence=sequence,
                        model_feedback=f"Duplicate action tool call id: {tool_call.id}",
                        frame_data={"reason": "duplicate_call_id"},
                    )
                )
                continue
            seen_call_ids.add(tool_call.id)
            if tool_call.kind is not ToolKind.ACTION:
                results.append(
                    _normalize_failure(
                        tool_call,
                        sequence=sequence,
                        model_feedback=(
                            "Expected an action tool call, but received a control or "
                            "uncategorized tool call."
                        ),
                        frame_data={"tool_kind": tool_call.kind.value if tool_call.kind else None},
                    )
                )
                continue
            if not catalog.has_action(tool_call.name):
                results.append(
                    _normalize_failure(
                        tool_call,
                        sequence=sequence,
                        model_feedback=f"Unknown action tool call: {tool_call.name}",
                    )
                )
                continue
            action = catalog.get_action(tool_call.name)
            hook_result = self._hooks.run(
                ActionNormalizeInput(
                    tool_call=tool_call,
                    action=action,
                    sequence=sequence,
                )
            )
            if hook_result is not None:
                results.append(hook_result)
                continue
            calls.append(
                ActionCall(
                    call_id=tool_call.id,
                    action_name=tool_call.name,
                    params=tool_call.arguments,
                    sequence=sequence,
                )
            )
        return ActionNormalization(
            calls=tuple(calls),
            results=tuple(results),
        )


@dataclass(frozen=True)
class ActionBatchPreparation:
    """Prepared action batch plus local preparation results."""

    batch: ActionBatch
    results: tuple[ActionResult, ...] = field(default_factory=tuple)
    phase_results: tuple[ActionPhaseResult, ...] = field(default_factory=tuple)


class ActionExecutionBuilder:
    """Build execution inputs from normalized action calls."""

    def prepare_batch(
        self,
        calls: tuple[ActionCall, ...],
        *,
        catalog: ActionCatalog,
        scope: RunScope,
        batch_id: str | None = None,
        turn_id: str = "",
        cycle_id: str = "",
        phase: ActionCyclePhase = ActionCyclePhase.PHASE3,
    ) -> ActionBatchPreparation:
        resolved_batch_id = batch_id or f"action_batch_{uuid4().hex[:8]}"
        executions: list[ActionExecution] = []
        results: list[ActionResult] = []
        seen_call_ids: set[str] = set()
        seen_sequences: set[int] = set()
        for call in calls:
            if call.call_id in seen_call_ids:
                results.append(
                    _prepare_failure(
                        call,
                        batch_id=resolved_batch_id,
                        stage_feedback=f"Duplicate action call id: {call.call_id}",
                        frame_data={"reason": "duplicate_call_id"},
                    )
                )
                continue
            if call.sequence in seen_sequences:
                results.append(
                    _prepare_failure(
                        call,
                        batch_id=resolved_batch_id,
                        stage_feedback=f"Duplicate action sequence: {call.sequence}",
                        frame_data={"reason": "duplicate_sequence"},
                    )
                )
                continue
            seen_call_ids.add(call.call_id)
            seen_sequences.add(call.sequence)
            if not catalog.has_action(call.action_name):
                results.append(
                    _prepare_failure(
                        call,
                        batch_id=resolved_batch_id,
                        stage_feedback=f"Unknown action during preparation: {call.action_name}",
                        frame_data={"reason": "unknown_action"},
                    )
                )
                continue
            action = catalog.get_action(call.action_name)
            timeout = action.runtime.timeout_seconds
            executions.append(
                ActionExecution(
                    action=action,
                    call=call,
                    framework=ActionFramework(
                        invoke_id=f"action_invoke_{uuid4().hex[:8]}",
                        batch_id=resolved_batch_id,
                        scope=scope,
                        domain=action.domain,
                        timeout_seconds=timeout,
                        turn_id=turn_id,
                        cycle_id=cycle_id,
                        phase=phase,
                    ),
                )
            )
        try:
            batch = ActionBatch(
                batch_id=resolved_batch_id,
                executions=tuple(executions),
            )
        except ActionInvariantError as exc:
            return ActionBatchPreparation(
                batch=ActionBatch(batch_id=resolved_batch_id),
                results=tuple(results),
                phase_results=(
                    ActionPhaseResult.failed(
                        phase=phase,
                        stage=ActionPhaseResultStage.PREPARE,
                        model_feedback="Action batch preparation failed.",
                        frame_data={
                            "error_type": type(exc).__name__,
                            "reason": "batch_invariant_error",
                        },
                        turn_id=turn_id,
                        cycle_id=cycle_id,
                    ),
                ),
            )
        return ActionBatchPreparation(
            batch=batch,
            results=tuple(results),
        )

    def build_batch(
        self,
        calls: tuple[ActionCall, ...],
        *,
        catalog: ActionCatalog,
        scope: RunScope,
        batch_id: str | None = None,
        turn_id: str = "",
        cycle_id: str = "",
        phase: ActionCyclePhase = ActionCyclePhase.PHASE3,
    ) -> ActionBatch:
        preparation = self.prepare_batch(
            calls,
            catalog=catalog,
            scope=scope,
            batch_id=batch_id,
            turn_id=turn_id,
            cycle_id=cycle_id,
            phase=phase,
        )
        if preparation.results or preparation.phase_results:
            raise ActionContractError("Action batch preparation produced local results")
        return preparation.batch


def _require_non_empty(value: str, field: str) -> None:
    if not value:
        raise ActionInvariantError(f"{field} must be non-empty")


def _normalize_failure(
    tool_call: ToolCallRecord,
    *,
    sequence: int,
    model_feedback: str,
    frame_data: JsonObject | None = None,
) -> ActionResult:
    return ActionResult.failed(
        call_id=tool_call.id,
        action_name=tool_call.name,
        stage=ActionResultStage.NORMALIZE,
        sequence=sequence,
        model_feedback=model_feedback,
        frame_data=frame_data,
    )


def _prepare_failure(
    call: ActionCall,
    *,
    batch_id: str,
    stage_feedback: str,
    frame_data: JsonObject,
) -> ActionResult:
    return ActionResult.failed(
        call_id=call.call_id,
        batch_id=batch_id,
        action_name=call.action_name,
        stage=ActionResultStage.PREPARE,
        sequence=call.sequence,
        model_feedback=stage_feedback,
        frame_data=frame_data,
    )
