"""
QueryAction Implementation for Query Loop.

Provides action execution and action metadata management.
QueryAction is responsible for instantiating and executing available actions
for the current query.

All handler resolution is delegated to the injected ActionRegistry,
which lazily caches handler instances.
"""

from typing import Any, Callable

from tinysoul.context.protocols import ContextProvider
from tinysoul.trap import (
    ActionNotFoundError,
)
from tinysoul.infra import EventLogger, NullSink
from tinysoul.action.framework.run_config import RunConfig

from .handler import ActionMeta, ActionMode
from .registry import ActionRegistry
from .validation import validate_action_input


class QueryAction:
    """
    Action manager for a single query using Command Pattern.

    Features:
    1. Initialize with available action names for the current query
    2. Execute actions by name with JSON parameters
    3. Query action metadata and details
    4. Actions are resolved from an injected ActionRegistry

    QueryAction does NOT maintain its own handler cache;
    all resolution is delegated to ActionRegistry, which lazily
    caches handler instances.
    """

    def __init__(
        self,
        available_actions: list[str],
        registry: ActionRegistry,
        logger: EventLogger | None = None,
    ):
        """
        Initialize QueryAction with available action names.

        Args:
            available_actions: List of action names to load from the registry
            registry: ActionRegistry instance to resolve handlers from
        """
        # Apply allowlist filtering so only requested actions are visible.
        self._registry: ActionRegistry = registry.with_allowlist(available_actions)
        self._logger = logger or EventLogger(sinks=[NullSink()])

    # ========================================================================
    # Command Pattern: Execute Action
    # ========================================================================

    def execute(
        self,
        action_name: str,
        action_input: dict,
        context_provider: ContextProvider,
        run_config: RunConfig,
    ) -> dict:
        """
        Execute an action by name with structured input.

        Args:
            action_name: Name of the action to execute
            action_input: Dict containing action parameters
            context_provider: Optional runtime context provider

        Returns:
            Result dict

        Raises:
            ActionNotFoundError: If action_name is not available
        """
        if not self._registry.is_available(action_name):
            raise ActionNotFoundError(
                f"Action '{action_name}' is not available. "
                f"Available actions: {self.list_available_action_names()}",
                action_name=action_name,
            )

        handler = self._registry.get_handler(action_name)
        detail = handler.get_detail()
        validate_action_input(action_name, detail.parameter_schema, action_input)

        resolved = handler.resolve_run_config(run_config)
        return handler.execute(action_input, context_provider, resolved)

    # ========================================================================
    # Query: Available Actions with Meta
    # ========================================================================

    def get_available_actions_meta(self) -> list[dict[str, Any]]:
        """
        Get all available actions with their ActionMeta (without ActionDetail).

        Returns:
            List of dictionaries containing action names and their metadata
        """
        from .handler import _applicability_to_text, _profile_to_text

        actions_meta = []
        for name in self._registry.get_available_action_names():
            handler = self._registry.get_handler(name)
            meta = handler.get_meta()
            actions_meta.append(
                {
                    "name": meta.name,
                    "description": meta.description,
                    "cluster": {
                        "type": meta.cluster.type.value,
                        "domain": meta.cluster.domain,
                    },
                    "profile": _profile_to_text(meta.profile),
                    "contract": {
                        "applicability": _applicability_to_text(
                            meta.contract.applicability
                        ),
                        "preconditions": meta.contract.preconditions,
                        "postconditions": {
                            "logical_state_effects": meta.contract.postconditions.logical_state_effects,
                            "physical_environment_effects": meta.contract.postconditions.physical_environment_effects,
                        },
                    },
                }
            )
        return actions_meta

    # ========================================================================
    # Query: Specific Action Detail
    # ========================================================================

    def get_selected_action_detail(self, action_name: str) -> dict[str, Any]:
        """
        Get ActionDetail for a specific action.

        Args:
            action_name: Name of the action

        Returns:
            Dictionary containing action detail

        Raises:
            ActionNotFoundError: If action_name is not found
        """
        if not self._registry.is_available(action_name):
            raise ActionNotFoundError(
                f"Action '{action_name}' is not available",
                action_name=action_name,
            )

        detail = self._registry.get_handler(action_name).get_detail()
        return {
            "parameter_schema": detail.parameter_schema,
            "examples": detail.examples,
            "edge_case_handling": detail.edge_case_handling,
        }

    # ========================================================================
    # Helper Methods
    # ========================================================================

    def is_action_available(self, action_name: str) -> bool:
        """Check if an action is available (registered and not filtered by allowlist)."""
        return self._registry.is_available(action_name)

    def list_available_action_names(self) -> list[str]:
        """Get list of all available action names."""
        return self._registry.get_available_action_names()

    def register_action(
        self,
        name: str,
        action_json: str,
        factory: Callable[[], Any],
        *,
        force: bool = False,
    ) -> None:
        """
        Register a new action into the current query's available action set.

        Registration is performed in *strict* mode: any instantiation or
        dependency failure raises ActionExecutionError so the caller
        (e.g. LLM via ErrorTrap) receives immediate feedback.

        The new action is immediately visible in subsequent turns via
        list_available_action_names() and get_available_actions_meta().
        """
        self._registry.register(name, action_json, factory, force=force, strict=True)

    def build_run_config(
        self,
        action_name: str,
        *,
        turn: int,
        execution_id: str,
        terminate_event,
    ) -> RunConfig:
        """Build and resolve a RunConfig for one action execution."""
        if not self._registry.is_available(action_name):
            raise ActionNotFoundError(
                f"Action '{action_name}' is not available",
                action_name=action_name,
            )
        handler = self._registry.get_handler(action_name)
        run_config = RunConfig(
            action_name=action_name,
            turn=turn,
            execution_id=execution_id,
            terminate_event=terminate_event,
        )
        return handler.resolve_run_config(run_config)

    def get_action_timeout(self, action_name: str) -> float:
        """Get the resolved execution timeout for an action."""
        import threading

        resolved = self.build_run_config(
            action_name,
            turn=0,
            execution_id="timeout_probe",
            terminate_event=threading.Event(),
        )
        return resolved.timeout or 0.0

    def get_action_meta(self, action_name: str) -> ActionMeta:
        """Get ActionMeta for a specific action.

        Args:
            action_name: Name of the action

        Returns:
            ActionMeta instance

        Raises:
            ActionNotFoundError: If action_name is not available
        """
        if not self._registry.is_available(action_name):
            raise ActionNotFoundError(
                f"Action '{action_name}' is not available",
                action_name=action_name,
            )
        return self._registry.get_handler(action_name).get_meta()

    def get_action_mode(self, action_name: str) -> ActionMode:
        """Get the action_mode (SINGLE_RUN / ONGOING) for a specific action.

        Args:
            action_name: Name of the action

        Returns:
            ActionMode enum value

        Raises:
            ActionNotFoundError: If action_name is not available
        """
        meta = self.get_action_meta(action_name)
        return meta.profile.action_mode

    def unregister_action(self, name: str) -> None:
        """Remove an action from the current query's available action set."""
        self._registry.unregister(name)
