"""Stage-aware action hook registry and pipelines."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.llm.tools import ToolCallRecord
from tinysoul.runtime import RuntimeException, RuntimeTransferInterrupt

from .errors import ActionContractError, ActionInvariantError
from .result import (
    ActionFailureDisposition,
    ActionLocalFailure,
    ActionResult,
    ActionResultStage,
)
from .schema import ActionSchemaValidationError, validate_action_params
from .specs import ActionSpec

if TYPE_CHECKING:
    from .call import ActionExecution
    from .executor import ActionExecutionContext


@dataclass(frozen=True)
class HookOutcome:
    """Outcome for one hook check."""

    ok: bool
    failure: ActionLocalFailure | None = None
    frame_data: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "frame_data", to_json_object(self.frame_data))
        if self.ok and self.failure is not None:
            raise ActionInvariantError("A successful hook cannot carry a failure")
        if not self.ok and self.failure is None:
            raise ActionInvariantError("A rejected hook requires a local failure")

    @property
    def model_feedback(self) -> str:
        return self.failure.feedback if self.failure is not None else ""

    @classmethod
    def success(cls) -> "HookOutcome":
        return cls(ok=True)

    @classmethod
    def failed(
        cls,
        model_feedback: str,
        *,
        reason: str = "hook_rejected",
        scope: str = "action.hook",
        disposition: ActionFailureDisposition = (
            ActionFailureDisposition.CHANGE_REQUEST
        ),
        constraint: JsonObject | None = None,
        frame_data: JsonObject | None = None,
    ) -> "HookOutcome":
        return cls(
            ok=False,
            failure=ActionLocalFailure(
                reason=reason,
                scope=scope,
                disposition=disposition,
                feedback=model_feedback,
                constraint=constraint or {},
            ),
            frame_data=frame_data or {},
        )


@dataclass(frozen=True)
class ActionNormalizeInput:
    """Input for a Phase2 normalize hook."""

    tool_call: ToolCallRecord
    action: ActionSpec
    sequence: int

    def __post_init__(self) -> None:
        if self.sequence <= 0:
            raise ActionInvariantError("ActionNormalizeInput.sequence must be positive")


class ActionNormalizeHook(Protocol):
    """Protocol for Phase2 action-call normalize hooks."""

    def check(self, item: ActionNormalizeInput) -> HookOutcome:
        """Check whether a model-side action tool call can become an ActionCall."""
        ...


class ActionExecutionHook(Protocol):
    """Protocol for Phase3 action execution hooks."""

    def check(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> HookOutcome:
        """Check whether an action execution can proceed."""
        ...


class SchemaNormalizeHook:
    """Built-in normalize hook that validates action parameters against schema."""

    def check(self, item: ActionNormalizeInput) -> HookOutcome:
        try:
            validate_action_params(item.tool_call.arguments, schema=item.action.tool.schema)
        except ActionSchemaValidationError as exc:
            return HookOutcome.failed(
                str(exc),
                reason="invalid_action_params",
                scope="action.schema",
                frame_data={"error_type": type(exc).__name__},
            )
        return HookOutcome.success()


class ActionHookRegistry:
    """Registry for reusable stage-specific action hooks."""

    def __init__(self) -> None:
        self._global_normalize_hooks: tuple[str, ...] = ()
        self._global_execution_hooks: tuple[str, ...] = ()
        self._domain_normalize_hooks: dict[str, tuple[str, ...]] = {}
        self._domain_execution_hooks: dict[str, tuple[str, ...]] = {}
        self._action_normalize_hooks: dict[str, tuple[str, ...]] = {}
        self._action_execution_hooks: dict[str, tuple[str, ...]] = {}
        self._normalize_hooks: dict[str, ActionNormalizeHook] = {}
        self._execution_hooks: dict[str, ActionExecutionHook] = {}

    def register_normalize_hook(self, name: str, hook: ActionNormalizeHook) -> None:
        _require_name(name, "normalize hook name")
        if name in self._normalize_hooks:
            raise ActionInvariantError(f"Action normalize hook already registered: {name}")
        self._normalize_hooks[name] = hook

    def register_execution_hook(self, name: str, hook: ActionExecutionHook) -> None:
        _require_name(name, "execution hook name")
        if name in self._execution_hooks:
            raise ActionInvariantError(f"Action execution hook already registered: {name}")
        self._execution_hooks[name] = hook

    def register_global_normalize(self, *names: str) -> None:
        self._global_normalize_hooks = (
            *self._global_normalize_hooks,
            *_names(names),
        )

    def register_global_execution(self, *names: str) -> None:
        self._global_execution_hooks = (
            *self._global_execution_hooks,
            *_names(names),
        )

    def register_domain_normalize(self, domain: str, *names: str) -> None:
        _require_name(domain, "domain")
        self._domain_normalize_hooks[domain] = (
            *self._domain_normalize_hooks.get(domain, ()),
            *_names(names),
        )

    def register_domain_execution(self, domain: str, *names: str) -> None:
        _require_name(domain, "domain")
        self._domain_execution_hooks[domain] = (
            *self._domain_execution_hooks.get(domain, ()),
            *_names(names),
        )

    def register_action_normalize(self, action_name: str, *names: str) -> None:
        _require_name(action_name, "action_name")
        self._action_normalize_hooks[action_name] = (
            *self._action_normalize_hooks.get(action_name, ()),
            *_names(names),
        )

    def register_action_execution(self, action_name: str, *names: str) -> None:
        _require_name(action_name, "action_name")
        self._action_execution_hooks[action_name] = (
            *self._action_execution_hooks.get(action_name, ()),
            *_names(names),
        )

    def normalize_hook_for(self, name: str) -> ActionNormalizeHook:
        try:
            return self._normalize_hooks[name]
        except KeyError as exc:
            raise ActionContractError(
                f"Unknown action normalize hook: {name}"
            ) from exc

    def execution_hook_for(self, name: str) -> ActionExecutionHook:
        try:
            return self._execution_hooks[name]
        except KeyError as exc:
            raise ActionContractError(
                f"Unknown action execution hook: {name}"
            ) from exc

    def normalize_names_for(self, action: ActionSpec) -> tuple[str, ...]:
        return (
            *self._global_normalize_hooks,
            *self._domain_normalize_hooks.get(action.domain, ()),
            *action.runtime.hooks.normalize_hooks,
            *self._action_normalize_hooks.get(action.name, ()),
        )

    def execution_names_for(self, action: ActionSpec) -> tuple[str, ...]:
        return (
            *self._global_execution_hooks,
            *self._domain_execution_hooks.get(action.domain, ()),
            *action.runtime.hooks.execution_hooks,
            *self._action_execution_hooks.get(action.name, ()),
        )


class ActionNormalizeHookPipeline:
    """Run built-in and configured Phase2 normalize hooks."""

    def __init__(
        self,
        registry: ActionHookRegistry | None = None,
        *,
        schema_hook: ActionNormalizeHook | None = None,
    ) -> None:
        self._registry = registry or ActionHookRegistry()
        self._schema_hook = schema_hook or SchemaNormalizeHook()

    @property
    def registry(self) -> ActionHookRegistry:
        return self._registry

    def run(
        self,
        item: ActionNormalizeInput,
    ) -> ActionResult | None:
        schema_result = self._run_hook(
            self._schema_hook,
            item,
            name="builtin.schema",
        )
        if schema_result is not None:
            return schema_result
        for name in self._registry.normalize_names_for(item.action):
            try:
                hook = self._registry.normalize_hook_for(name)
            except (RuntimeException, RuntimeTransferInterrupt):
                raise
            except Exception as exc:
                return _normalize_hook_failure(
                    item,
                    reason="normalize_hook_unavailable",
                    model_feedback=f"Action normalize hook is not available: {name}",
                    frame_data={
                        "hook": name,
                        "error_type": type(exc).__name__,
                    },
                )
            hook_result = self._run_hook(
                hook,
                item,
                name=name,
            )
            if hook_result is not None:
                return hook_result
        return None

    def _run_hook(
        self,
        hook: ActionNormalizeHook,
        item: ActionNormalizeInput,
        *,
        name: str,
    ) -> ActionResult | None:
        try:
            outcome = hook.check(item)
        except (RuntimeException, RuntimeTransferInterrupt):
            raise
        except Exception as exc:
            return _normalize_hook_failure(
                item,
                reason="normalize_hook_failed",
                model_feedback=f"Action normalize hook failed: {name}",
                frame_data={
                    "hook": name,
                    "error_type": type(exc).__name__,
                },
            )
        if not outcome.ok:
            assert outcome.failure is not None
            return _normalize_hook_failure(
                item,
                failure=outcome.failure,
                frame_data={"hook": name, **outcome.frame_data},
            )
        return None


class ActionExecutionHookPipeline:
    """Run configured Phase3 execution hooks."""

    def __init__(self, registry: ActionHookRegistry | None = None) -> None:
        self._registry = registry or ActionHookRegistry()

    @property
    def registry(self) -> ActionHookRegistry:
        return self._registry

    def run(
        self,
        execution: ActionExecution,
        *,
        context: ActionExecutionContext,
    ) -> ActionResult | None:
        for name in self._registry.execution_names_for(execution.action):
            try:
                hook = self._registry.execution_hook_for(name)
            except (RuntimeException, RuntimeTransferInterrupt):
                raise
            except Exception as exc:
                return _execution_hook_failure(
                    execution,
                    reason="execution_hook_unavailable",
                    model_feedback=f"Action execution hook is not available: {name}",
                    frame_data={
                        "hook": name,
                        "error_type": type(exc).__name__,
                    },
                )
            try:
                outcome = hook.check(execution, context)
            except (RuntimeException, RuntimeTransferInterrupt):
                raise
            except Exception as exc:
                return _execution_hook_failure(
                    execution,
                    reason="execution_hook_failed",
                    model_feedback=f"Action execution hook failed: {name}",
                    frame_data={
                        "hook": name,
                        "error_type": type(exc).__name__,
                    },
                )
            if not outcome.ok:
                assert outcome.failure is not None
                return _execution_hook_failure(
                    execution,
                    failure=outcome.failure,
                    frame_data={"hook": name, **outcome.frame_data},
                )
        return None


def _normalize_hook_failure(
    item: ActionNormalizeInput,
    *,
    model_feedback: str | None = None,
    reason: str | None = None,
    failure: ActionLocalFailure | None = None,
    frame_data: JsonObject,
) -> ActionResult:
    local_failure = _pipeline_failure(
        failure,
        reason=reason,
        scope="action.normalize_hook",
        model_feedback=model_feedback,
    )
    return ActionResult.failed(
        call_id=item.tool_call.id,
        action_name=item.tool_call.name,
        stage=ActionResultStage.NORMALIZE,
        sequence=item.sequence,
        failure=local_failure,
        frame_data=frame_data,
    )


def _execution_hook_failure(
    execution: ActionExecution,
    *,
    model_feedback: str | None = None,
    reason: str | None = None,
    failure: ActionLocalFailure | None = None,
    frame_data: JsonObject,
) -> ActionResult:
    local_failure = _pipeline_failure(
        failure,
        reason=reason,
        scope="action.execution_hook",
        model_feedback=model_feedback,
    )
    return ActionResult.failed(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        stage=ActionResultStage.HOOK,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        failure=local_failure,
        frame_data=frame_data,
    )


def _pipeline_failure(
    failure: ActionLocalFailure | None,
    *,
    reason: str | None,
    scope: str,
    model_feedback: str | None,
) -> ActionLocalFailure:
    if failure is not None:
        if reason is not None or model_feedback is not None:
            raise ActionInvariantError(
                "A hook failure cannot combine an owner failure with pipeline facts"
            )
        return failure
    if not reason or not model_feedback:
        raise ActionInvariantError("A pipeline-owned hook failure requires facts")
    return ActionLocalFailure(
        reason=reason,
        scope=scope,
        disposition=ActionFailureDisposition.CHANGE_REQUEST,
        feedback=model_feedback,
    )


def _names(names: tuple[str, ...]) -> tuple[str, ...]:
    for name in names:
        _require_name(name, "hook name")
    return tuple(names)


def _require_name(value: str, field: str) -> None:
    if not value:
        raise ActionInvariantError(f"{field} must be non-empty")
