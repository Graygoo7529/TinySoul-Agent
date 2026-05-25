"""
Action registry for TinySoul.

Instance-level (not global) registry that maps action names to
(action_json_str, factory) pairs.
"""

from typing import Any, Callable

from tinysoul.trap import ActionExecutionError, ActionInputError
from tinysoul.infra.capabilities import (
    ActionDependency,
    EnvironmentCapabilities,
)
from .validation import validate_action_metadata


class ActionRegistry:
    """
    Registry for action handlers.

    Each QueryLoop / test gets its own instance. No module-level
    global registry.

    Handler instances are lazily cached so repeated lookups do not
    re-instantiate the same action handler.
    """

    def __init__(self, env_caps: EnvironmentCapabilities | None = None):
        self._registry: dict[str, tuple[str, Callable]] = {}
        self._handler_cache: dict[str, Any] = {}
        self._allowlist: set[str] | None = None
        self._env_caps = env_caps or EnvironmentCapabilities.probe()
        self._skipped: list[tuple[str, list[ActionDependency]]] = []

    def is_registered(self, name: str) -> bool:
        return name in self._registry

    def get_action_json(self, name: str) -> str:
        if name not in self._registry:
            raise ActionExecutionError(f"Action '{name}' is not registered")
        return self._registry[name][0]

    def get_factory(self, name: str) -> Callable:
        if name not in self._registry:
            raise ActionExecutionError(f"Action '{name}' is not registered")
        return self._registry[name][1]

    def get_handler(self, name: str):
        if name not in self._handler_cache:
            factory = self.get_factory(name)
            self._handler_cache[name] = factory()
        return self._handler_cache[name]

    def get_all_action_names(self) -> list[str]:
        return list(self._registry.keys())

    def is_available(self, name: str) -> bool:
        registered = self.is_registered(name)
        if self._allowlist is None:
            return registered
        return registered and name in self._allowlist

    def get_available_action_names(self) -> list[str]:
        return sorted(name for name in self._registry if self.is_available(name))

    def with_allowlist(self, names: list[str]):
        """Return a new registry view with the given allowlist."""
        view = object.__new__(ActionRegistry)
        view._registry = self._registry
        view._handler_cache = self._handler_cache
        view._allowlist = set(names)
        view._env_caps = self._env_caps
        view._skipped = self._skipped
        return view

    def register(
        self,
        name: str,
        action_json: str,
        factory: Callable,
        *,
        force: bool = False,
        strict: bool = False,
    ) -> None:
        """
        Register an action with optional dependency checking.

        Args:
            name: Unique action name.
            action_json: ACTION_JSON schema string.
            factory: Callable that returns an ActionHandler instance.
            force: If True, overwrite an existing registration.
            strict: If True, dependency / instantiation failures raise
                ActionExecutionError instead of being silently skipped.
                Use ``strict=True`` for runtime (dynamic) registrations
                where the caller must know immediately if the action
                cannot be made available.
        """
        if name in self._registry and not force:
            raise ActionInputError(f"Action '{name}' is already registered")

        # Clear stale cached handler when force-updating
        if name in self._handler_cache and force:
            del self._handler_cache[name]

        # Dependency check: skip actions whose required deps are missing.
        # If factory() itself fails (e.g. ImportError due to missing deps),
        # treat it as a dependency failure and DO NOT register.
        try:
            handler = factory()
        except Exception as exc:
            dep = ActionDependency(
                "instantiation", f"{type(exc).__name__}: {exc}", optional=False
            )
            if strict:
                raise ActionExecutionError(
                    f"Action '{name}' instantiation failed: {exc}"
                ) from exc
            self._skipped.append((name, [dep]))
            return

        # Validate ACTION_JSON structure before accepting registration.
        try:
            validate_action_metadata(action_json)
        except ActionExecutionError as exc:
            if strict:
                raise
            dep = ActionDependency("metadata", str(exc), optional=False)
            self._skipped.append((name, [dep]))
            return

        runtime_config = getattr(handler, "get_runtime_config", lambda: None)()
        if runtime_config is not None:
            missing = self._env_caps.unsatisfied(runtime_config.dependencies)
            if missing:
                if strict:
                    dep_str = ", ".join(f"{d.type}:{d.name}" for d in missing)
                    raise ActionExecutionError(
                        f"Action '{name}' has unsatisfied dependencies: [{dep_str}]"
                    )
                self._skipped.append((name, missing))
                return

        self._registry[name] = (action_json, factory)
        # Newly registered actions are automatically available in views
        # that have an allowlist, since they are registered at runtime
        # for the current query loop.
        if self._allowlist is not None:
            self._allowlist.add(name)

    def get_skipped(self) -> list[tuple[str, list[ActionDependency]]]:
        """Return actions skipped during registration due to missing dependencies."""
        return self._skipped.copy()

    def unregister(self, name: str) -> None:
        if name in self._registry:
            del self._registry[name]
        if name in self._handler_cache:
            del self._handler_cache[name]

    def register_action_class(self, action_cls, *, force: bool = False, strict: bool = False) -> None:
        """Register an ActionBase subclass using its class attributes.

        Convenience helper that eliminates the repetitive ``register_to``
        boilerplate in action handler modules.
        """
        self.register(
            action_cls.action_name,
            action_cls.ACTION_JSON,
            lambda: action_cls(),
            force=force,
            strict=strict,
        )
