"""Action input hook registry and pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from tinysoul.infra.json import JsonObject, to_json_object

from .call import ActionExecution
from .catalog import ActionCatalog
from .result import ActionResult, ActionResultStage


@dataclass(frozen=True)
class HookOutcome:
    """Outcome for one hook check."""

    ok: bool
    model_feedback: str = ""
    frame_data: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "frame_data", to_json_object(self.frame_data))

    @classmethod
    def success(cls) -> "HookOutcome":
        return cls(ok=True)

    @classmethod
    def failed(
        cls,
        model_feedback: str,
        *,
        frame_data: JsonObject | None = None,
    ) -> "HookOutcome":
        return cls(
            ok=False,
            model_feedback=model_feedback,
            frame_data=frame_data or {},
        )


class ActionHook(Protocol):
    """Protocol for action input hooks."""

    def check(self, execution: ActionExecution, context: object) -> HookOutcome:
        """Check whether an action execution can proceed."""
        ...


class ActionHookRegistry:
    """Registry for reusable action hooks."""

    def __init__(self) -> None:
        self._global_hooks: tuple[str, ...] = ()
        self._domain_hooks: dict[str, tuple[str, ...]] = {}
        self._action_hooks: dict[str, tuple[str, ...]] = {}
        self._hooks: dict[str, ActionHook] = {}

    def register_hook(self, name: str, hook: ActionHook) -> None:
        _require_name(name, "hook name")
        if name in self._hooks:
            raise ValueError(f"Action hook already registered: {name}")
        self._hooks[name] = hook

    def register_global(self, *names: str) -> None:
        self._global_hooks = (*self._global_hooks, *_names(names))

    def register_domain(self, domain: str, *names: str) -> None:
        _require_name(domain, "domain")
        self._domain_hooks[domain] = (
            *self._domain_hooks.get(domain, ()),
            *_names(names),
        )

    def register_action(self, action_name: str, *names: str) -> None:
        _require_name(action_name, "action_name")
        self._action_hooks[action_name] = (
            *self._action_hooks.get(action_name, ()),
            *_names(names),
        )

    def hook_for(self, name: str) -> ActionHook:
        try:
            return self._hooks[name]
        except KeyError as exc:
            raise KeyError(f"Unknown action hook: {name}") from exc

    def names_for(
        self,
        *,
        domain: str,
        action_name: str,
        runtime_hooks: tuple[str, ...],
    ) -> tuple[str, ...]:
        return (
            *self._global_hooks,
            *self._domain_hooks.get(domain, ()),
            *runtime_hooks,
            *self._action_hooks.get(action_name, ()),
        )


class ActionHookPipeline:
    """Run global, domain, runtime and action-specific hooks."""

    def __init__(self, registry: ActionHookRegistry | None = None) -> None:
        self._registry = registry or ActionHookRegistry()

    @property
    def registry(self) -> ActionHookRegistry:
        return self._registry

    def run(
        self,
        execution: ActionExecution,
        *,
        catalog: ActionCatalog,
        context: object,
    ) -> ActionResult | None:
        action = catalog.get_action(execution.call.action_name)
        names = self._registry.names_for(
            domain=action.domain,
            action_name=action.name,
            runtime_hooks=action.runtime.hooks,
        )
        for name in names:
            outcome = self._registry.hook_for(name).check(execution, context)
            if not outcome.ok:
                return ActionResult.failed(
                    invoke_id=execution.framework.invoke_id,
                    action_name=execution.call.action_name,
                    stage=ActionResultStage.HOOK,
                    model_feedback=outcome.model_feedback
                    or f"Action hook failed: {name}",
                    frame_data={"hook": name, **outcome.frame_data},
                )
        return None


def _names(names: tuple[str, ...]) -> tuple[str, ...]:
    for name in names:
        _require_name(name, "hook name")
    return tuple(names)


def _require_name(value: str, field: str) -> None:
    if not value:
        raise ValueError(f"{field} must be non-empty")
